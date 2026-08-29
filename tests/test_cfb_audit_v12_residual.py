from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sportsedge.sports.cfb.decision_policy import live_candidate_decision
from sportsedge.sports.cfb.historical_market import HistoricalQuote, audit_historical_market_rows, declare_closing_only_archive
from sportsedge.sports.cfb.historical_readiness import assess_cfb_historical_readiness
from sportsedge.sports.cfb.model_promotion_v1 import evaluate_cfb_model_v2_promotion
from sportsedge.sports.cfb.run_machine import DEFAULT_QUOTE_PAIR_SKEW_SECONDS, DEFAULT_QUOTE_TTL_SECONDS


UTC = timezone.utc
START = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)


def comparison(market: str, **overrides):
    row = {
        "market": market,
        "outer_forward_seasons": 4,
        "predictive_rows": 1200,
        "economic_candidates": 250,
        "baseline_brier": 0.220,
        "candidate_brier": 0.210,
        "paired_brier_delta_upper_95": -0.002,
        "baseline_logloss": 0.640,
        "candidate_logloss": 0.620,
        "paired_logloss_delta_upper_95": -0.003,
        "baseline_ece": 0.020,
        "candidate_ece": 0.018,
        "candidate_calibration_slope": 1.00,
        "candidate_calibration_intercept": 0.00,
        "baseline_mean_clv": 0.006,
        "candidate_mean_clv": 0.008,
        "baseline_roi_after_vig": 0.010,
        "candidate_roi_after_vig": 0.020,
        "recent_two_seasons_both_metrics_worse": False,
        "candidate_truth_gate_status": "OFFICIAL",
        "attestations_passed": True,
        "baseline_key_number_max_abs_error": 0.010 if market == "SPREAD" else None,
        "candidate_key_number_max_abs_error": 0.009 if market == "SPREAD" else None,
    }
    row.update(overrides)
    return row


def feature_row(season: int, game_id: str):
    kickoff = START.replace(year=season)
    return {
        "season": season,
        "game_id": game_id,
        "feature_contract": "CFB_JOINT_GAME_FEATURES_V2",
        "feature_asof_ts": (kickoff - timedelta(hours=2)).isoformat(),
        "game_start_ts": kickoff.isoformat(),
    }


def quote(quote_id: str, season: int, market: str, side: str, captured: datetime, *, closing: bool, line):
    return HistoricalQuote(
        quote_id=quote_id,
        game_id=f"g{season}",
        season=season,
        market=market,
        side=side,
        line=line,
        american_odds=-110.0,
        book="PINNACLE",
        provider="PINNACLE",
        captured_ts=captured.isoformat(),
        source_artifact_id="test-source",
        is_closing=closing,
    )


class PromotionPolicyTests(unittest.TestCase):
    def test_v2_promotion_is_non_discretionary_and_requires_all_markets(self):
        passed = evaluate_cfb_model_v2_promotion([
            comparison("MONEYLINE"), comparison("SPREAD"), comparison("TOTAL")
        ])
        self.assertTrue(passed.promote)

        failed = evaluate_cfb_model_v2_promotion([
            comparison("MONEYLINE"),
            comparison("SPREAD", candidate_key_number_max_abs_error=0.030),
            comparison("TOTAL", candidate_truth_gate_status="FAILED"),
        ])
        self.assertFalse(failed.promote)
        self.assertIn("SPREAD:KEY_NUMBER_CALIBRATION_OUT_OF_BOUNDS", failed.failures)
        self.assertIn("TOTAL:CANDIDATE_TRUTH_GATE_NOT_OFFICIAL", failed.failures)

    def test_v2_cannot_win_on_point_estimate_without_supported_improvement(self):
        failed = evaluate_cfb_model_v2_promotion([
            comparison("MONEYLINE", paired_brier_delta_upper_95=0.001, paired_logloss_delta_upper_95=0.002),
            comparison("SPREAD"), comparison("TOTAL")
        ])
        self.assertIn("MONEYLINE:NO_STATISTICALLY_SUPPORTED_PRIMARY_IMPROVEMENT", failed.failures)


class QuoteAndShadowFirewallTests(unittest.TestCase):
    def test_hashed_quote_sync_config_matches_live_engine_defaults(self):
        config = json.loads(Path("config/cfb_quote_sync_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(config["live"]["max_quote_age_seconds"], DEFAULT_QUOTE_TTL_SECONDS)
        self.assertEqual(config["live"]["max_pair_timestamp_skew_seconds"], DEFAULT_QUOTE_PAIR_SKEW_SECONDS)
        self.assertTrue(config["live"]["invalidate_both_sides_if_either_side_fails"])

    def test_shadow_status_cannot_authorize_live_official_bet(self):
        decision = live_candidate_decision(
            edge=0.08,
            ev_per_dollar=0.10,
            quote_fresh=True,
            two_sided=True,
            exposure_ok=True,
            data_quality_ok=True,
            coverage_ok=True,
            override_log_complete=True,
            policy_sha_ok=True,
            historical_status="SHADOW_QUALIFIED",
        )
        self.assertEqual(decision.status, "BLOCKED")
        self.assertEqual(decision.reason, "HISTORICAL_MARKET_NOT_OFFICIAL")


class HistoricalReadinessTests(unittest.TestCase):
    def test_closing_only_archive_can_benchmark_but_cannot_support_clv_replay(self):
        seasons = (2022, 2023, 2024, 2025)
        features = [feature_row(season, f"g{season}") for season in seasons]
        close_quotes = []
        for season in seasons:
            captured = START.replace(year=season) - timedelta(minutes=5)
            for market, sides, line in (
                ("MONEYLINE", ("HOME", "AWAY"), None),
                ("SPREAD", ("HOME", "AWAY"), -3.0),
                ("TOTAL", ("OVER", "UNDER"), 50.0),
            ):
                for i, side in enumerate(sides):
                    close_quotes.append(quote(f"{season}-{market}-{i}", season, market, side, captured, closing=True, line=line))
        archive = declare_closing_only_archive(archive_id="closing-only", rows=close_quotes)
        readiness = assess_cfb_historical_readiness(features, archive, required_seasons=seasons)
        self.assertTrue(readiness.walk_forward_ready)
        self.assertFalse(readiness.clv_replay_ready)
        self.assertIn("MARKET_ARCHIVE_CLOSING_ONLY_OR_NO_INTRADAY_PATH", readiness.blockers)

    def test_decision_to_close_exact_contract_paths_unlock_clv_readiness(self):
        seasons = (2022, 2023, 2024, 2025)
        features = [feature_row(season, f"g{season}") for season in seasons]
        quotes = []
        for season in seasons:
            kickoff = START.replace(year=season)
            for market, sides, line in (
                ("MONEYLINE", ("HOME", "AWAY"), None),
                ("SPREAD", ("HOME", "AWAY"), -3.0),
                ("TOTAL", ("OVER", "UNDER"), 50.0),
            ):
                for closing, captured in ((False, kickoff - timedelta(hours=2)), (True, kickoff - timedelta(minutes=5))):
                    for i, side in enumerate(sides):
                        quote_id = f"{season}-{market}-{int(closing)}-{i}"
                        quotes.append(quote(quote_id, season, market, side, captured, closing=closing, line=line))
        archive = audit_historical_market_rows(quotes, archive_id="paired-path")
        readiness = assess_cfb_historical_readiness(features, archive, required_seasons=seasons)
        self.assertTrue(readiness.walk_forward_ready)
        self.assertTrue(readiness.clv_replay_ready)
        self.assertEqual(readiness.blockers, ())


if __name__ == "__main__":
    unittest.main()
