from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import unittest

from sportsedge.sports.nfl.m2 import (
    NFL_M2_FEATURE_CONTRACT,
    fit_nfl_m2_score_model,
)
from sportsedge.sports.nfl.model_artifact import build_nfl_m2_model_artifact
from sportsedge.sports.nfl.run_machine import NFLRunMachineError, run_nfl_machine

CODE_SHA = "a" * 40
TRAINING_SHA = "b" * 64
LIVE_SHA = "c" * 64
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
START = "2026-09-10T13:00:00+00:00"


def _features(*, asof: str = "2026-09-10T11:50:00+00:00", bump: float = 0.0) -> dict:
    return {
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "qb_id": "qb-1",
        "feature_asof_ts": asof,
        "adj_off_epa": 0.10 + bump,
        "adj_def_epa": -0.02 + bump,
        "pass_epa": 0.14 + bump,
        "rush_epa": 0.03 + bump,
        "pressure_for": 0.31 + bump,
        "pressure_allowed": 0.29 + bump,
        "success_rate": 0.44 + bump,
        "explosive_rate": 0.11 + bump,
        "rest_diff_days": 0.0,
        "travel_miles": 120.0 + bump,
        "timezone_crossings": 0.0,
        "short_week": 0.0,
        "bye_week": 0.0,
        "wind_mph": 6.0 + bump,
        "roof_closed": 0.0,
        "qb_adjustment": 0.02 + bump,
        "prior_efficiency": 0.01 + bump,
        "prior_weight": 0.35,
    }


def _training_row(score_home: int, score_away: int, season: int, bump: float) -> dict:
    return {
        "season": season,
        "home_features": _features(asof="2025-12-01T12:00:00+00:00", bump=bump),
        "away_features": _features(asof="2025-12-01T12:00:00+00:00", bump=-bump),
        "home_score": score_home,
        "away_score": score_away,
    }


def _artifact() -> dict:
    model = fit_nfl_m2_score_model([
        _training_row(21, 17, 2023, 0.00),
        _training_row(31, 14, 2023, 0.01),
        _training_row(17, 24, 2024, 0.02),
        _training_row(27, 27, 2024, 0.03),
        _training_row(20, 30, 2025, 0.04),
    ])
    return build_nfl_m2_model_artifact(
        model,
        code_git_sha=CODE_SHA,
        source_manifest_sha256=TRAINING_SHA,
    )


def _live() -> dict:
    return {
        "sport": "nfl",
        "source_manifest_sha256": LIVE_SHA,
        "asof_ts": "2026-09-10T11:58:00+00:00",
        "games": [{
            "game_id": "nfl-2026-01-gb-chi",
            "game_start_ts": START,
            "home_team": "CHI",
            "away_team": "GB",
            "provider_home_team": "Chicago Bears",
            "provider_away_team": "Green Bay Packers",
            "home_features": _features(bump=0.02),
            "away_features": _features(bump=-0.01),
        }],
    }


def _event(*, spread: float = -2.5, total: float = 44.5) -> dict:
    return {
        "id": "provider-event-1",
        "sport_key": "americanfootball_nfl",
        "commence_time": START,
        "home_team": "Chicago Bears",
        "away_team": "Green Bay Packers",
        "bookmakers": [{
            "key": "draftkings",
            "title": "DraftKings",
            "last_update": "2026-09-10T11:59:00+00:00",
            "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": "Chicago Bears", "price": -125},
                    {"name": "Green Bay Packers", "price": 105},
                ]},
                {"key": "spreads", "outcomes": [
                    {"name": "Chicago Bears", "point": spread, "price": -110},
                    {"name": "Green Bay Packers", "point": -spread, "price": -110},
                ]},
                {"key": "totals", "outcomes": [
                    {"name": "Over", "point": total, "price": -108},
                    {"name": "Under", "point": total, "price": -112},
                ]},
            ],
        }],
    }


def _odds(*, observed: str = "2026-09-10T11:59:00+00:00", spread: float = -2.5, total: float = 44.5) -> dict:
    return {
        "source": "fixture",
        "observed_at": observed,
        "events": [_event(spread=spread, total=total)],
    }


class NFLRunMachineTests(unittest.TestCase):
    def test_manual_converges_on_six_priced_but_blocked_game_market_rows(self):
        report = run_nfl_machine(
            mode="MANUAL",
            model_artifact=_artifact(),
            runtime_code_git_sha=CODE_SHA,
            now=NOW,
            live_features=_live(),
            odds_snapshot=_odds(),
        )
        self.assertEqual(report.mode, "MANUAL")
        self.assertEqual(report.run_status, "BLOCKED")
        self.assertEqual(len(report.results), 6)
        self.assertEqual(report.summary["official_bets"], 0)
        self.assertEqual(report.summary["markets_seen"], ["MONEYLINE", "SPREAD", "TOTAL"])
        self.assertTrue(all(row.engine_status == "PRICED" for row in report.results))
        self.assertTrue(all(row.bet_status == "BLOCKED" for row in report.results))
        self.assertTrue(all(row.reason == "NFL_PROMOTION_EVIDENCE_REQUIRED" for row in report.results))
        self.assertTrue(all(row.training_source_manifest_sha256 == TRAINING_SHA for row in report.results))
        self.assertTrue(all(row.live_feature_source_manifest_sha256 == LIVE_SHA for row in report.results))
        self.assertNotEqual(report.training_source_manifest_sha256, report.live_feature_source_manifest_sha256)
        self.assertEqual(len({row.distribution_sha256 for row in report.results}), 1)

    def test_quote_older_than_180_seconds_fails_closed_without_market_economics(self):
        report = run_nfl_machine(
            mode="MANUAL",
            model_artifact=_artifact(),
            runtime_code_git_sha=CODE_SHA,
            now=NOW,
            live_features=_live(),
            odds_snapshot=_odds(observed="2026-09-10T11:56:00+00:00"),
        )
        self.assertEqual(report.summary["stale"], 6)
        for row in report.results:
            self.assertEqual(row.reason, "NFL_QUOTE_STALE")
            self.assertIsNone(row.fair_market_p)
            self.assertIsNone(row.raw_implied_p)
            self.assertIsNone(row.edge)
            self.assertIsNone(row.ev_per_dollar)
            self.assertEqual(row.bet_status, "BLOCKED")

    def test_runtime_code_sha_must_match_frozen_model_artifact(self):
        with self.assertRaisesRegex(NFLRunMachineError, "NFL_M2_MODEL_ARTIFACT_CODE_SHA_MISMATCH"):
            run_nfl_machine(
                mode="MANUAL",
                model_artifact=_artifact(),
                runtime_code_git_sha="d" * 40,
                now=NOW,
                live_features=_live(),
                odds_snapshot=_odds(),
            )

    def test_feature_snapshot_and_side_features_are_pit_bound(self):
        live = _live()
        live["games"][0]["home_features"]["feature_asof_ts"] = "2026-09-10T11:59:00+00:00"
        with self.assertRaisesRegex(NFLRunMachineError, "NFL_M2_HOME_FEATURE_AFTER_SNAPSHOT"):
            run_nfl_machine(
                mode="MANUAL",
                model_artifact=_artifact(),
                runtime_code_git_sha=CODE_SHA,
                now=NOW,
                live_features=live,
                odds_snapshot=_odds(),
            )

    def test_stale_feature_snapshot_is_rejected_before_model_execution(self):
        live = _live()
        live["asof_ts"] = "2026-09-10T09:59:00+00:00"
        with self.assertRaisesRegex(NFLRunMachineError, "NFL_LIVE_FEATURE_SNAPSHOT_STALE"):
            run_nfl_machine(
                mode="MANUAL",
                model_artifact=_artifact(),
                runtime_code_git_sha=CODE_SHA,
                now=NOW,
                live_features=live,
                odds_snapshot=_odds(),
            )

    def test_future_quote_observation_is_rejected(self):
        with self.assertRaisesRegex(NFLRunMachineError, "NFL_ODDS_OBSERVED_FROM_FUTURE"):
            run_nfl_machine(
                mode="MANUAL",
                model_artifact=_artifact(),
                runtime_code_git_sha=CODE_SHA,
                now=NOW,
                live_features=_live(),
                odds_snapshot=_odds(observed="2026-09-10T12:01:00+00:00"),
            )

    def test_market_line_changes_do_not_change_underlying_distribution(self):
        left = run_nfl_machine(
            mode="MANUAL",
            model_artifact=_artifact(),
            runtime_code_git_sha=CODE_SHA,
            now=NOW,
            live_features=_live(),
            odds_snapshot=_odds(spread=-2.5, total=44.5),
        )
        right = run_nfl_machine(
            mode="MANUAL",
            model_artifact=_artifact(),
            runtime_code_git_sha=CODE_SHA,
            now=NOW,
            live_features=_live(),
            odds_snapshot=_odds(spread=-6.5, total=51.5),
        )
        self.assertEqual(
            {row.distribution_sha256 for row in left.results},
            {row.distribution_sha256 for row in right.results},
        )
        left_ml = {(row.side, row.model_p) for row in left.results if row.market == "MONEYLINE"}
        right_ml = {(row.side, row.model_p) for row in right.results if row.market == "MONEYLINE"}
        self.assertEqual(left_ml, right_ml)

    def test_market_derived_feature_is_rejected_by_m2(self):
        live = _live()
        live["games"][0]["home_features"]["spread"] = -2.5
        with self.assertRaisesRegex(NFLRunMachineError, "M2_MARKET_DATA_PROHIBITED"):
            run_nfl_machine(
                mode="MANUAL",
                model_artifact=_artifact(),
                runtime_code_git_sha=CODE_SHA,
                now=NOW,
                live_features=live,
                odds_snapshot=_odds(),
            )

    def test_hybrid_supports_operator_odds_with_automatic_features(self):
        calls = []
        report = run_nfl_machine(
            mode="HYBRID",
            model_artifact=_artifact(),
            runtime_code_git_sha=CODE_SHA,
            now=NOW,
            odds_snapshot=_odds(),
            feature_builder=lambda: calls.append("features") or _live(),
        )
        self.assertEqual(calls, ["features"])
        self.assertEqual(report.mode, "HYBRID")
        self.assertEqual(len(report.results), 6)

    def test_automatic_acquires_both_inputs_then_uses_same_canonical_path(self):
        calls = []
        automatic = run_nfl_machine(
            mode="AUTOMATIC",
            model_artifact=_artifact(),
            runtime_code_git_sha=CODE_SHA,
            now=NOW,
            feature_builder=lambda: calls.append("features") or _live(),
            odds_fetcher=lambda: calls.append("odds") or _odds(),
        )
        manual = run_nfl_machine(
            mode="MANUAL",
            model_artifact=_artifact(),
            runtime_code_git_sha=CODE_SHA,
            now=NOW,
            live_features=_live(),
            odds_snapshot=_odds(),
        )
        self.assertEqual(calls, ["features", "odds"])
        self.assertEqual(
            [(r.market, r.side, r.model_p, r.distribution_sha256) for r in automatic.results],
            [(r.market, r.side, r.model_p, r.distribution_sha256) for r in manual.results],
        )

    def test_hybrid_requires_exactly_one_operator_snapshot(self):
        with self.assertRaisesRegex(NFLRunMachineError, "NFL_HYBRID_REQUIRES_EXACTLY_ONE_OPERATOR_SNAPSHOT"):
            run_nfl_machine(
                mode="HYBRID",
                model_artifact=_artifact(),
                runtime_code_git_sha=CODE_SHA,
                now=NOW,
                live_features=_live(),
                odds_snapshot=_odds(),
            )


if __name__ == "__main__":
    unittest.main()
