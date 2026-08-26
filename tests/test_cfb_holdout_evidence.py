from __future__ import annotations

import copy
import unittest

from sportsedge.sports.cfb.holdout_evidence import (
    CFBHoldoutEvidenceError,
    analyze_cfb_holdout,
)

H = "a" * 64
M = "b" * 64


def row(game_id="g1", season=2024, odds_source="summary_pickcenter"):
    return {
        "game_id": game_id,
        "season": season,
        "seed": 12345,
        "n_paths": 20000,
        "weather_evidence_class": "ARCHIVED_PREGAME_WEATHER",
        "predictive_features": {
            "neutral_site": False,
            "home_metrics": {"off_ppa_rush": 0.12},
            "away_metrics": {"off_ppa_rush": 0.08},
            "weather": {"wind_speed": 7.0, "temperature": 76.0, "game_indoor": False},
        },
        "home_score": 31,
        "away_score": 24,
        "predicted_home_mean": 29.0,
        "predicted_away_mean": 23.0,
        "home_win_p": 0.64,
        "benchmark": {
            "odds_source": odds_source,
            "home_team_spread": -3.5,
            "over_under": 49.5,
        },
        "spread_home_cover_p": 0.57,
        "spread_push_p": 0.00,
        "total_over_p": 0.55,
        "total_push_p": 0.00,
    }


def analyze(rows, **kwargs):
    common = dict(
        model_artifact_sha256=M,
        train_seasons=(2021, 2022, 2023),
        train_game_ids=("t1", "t2"),
        source_manifest_sha256s=(H,),
        source_evidence_class="CHECKSUM_VERIFIED_SPORTSDATAVERSE_RELEASE",
    )
    common.update(kwargs)
    return analyze_cfb_holdout(rows, **common)


class HoldoutEvidenceTests(unittest.TestCase):
    def test_happy_path_is_evidence_complete_but_not_promoted(self):
        out = analyze([row("g1"), row("g2")])
        self.assertEqual(out["evidence_state"], "COMPLETE")
        self.assertEqual(out["promotion_state"], "BLOCKED")
        self.assertIn("CFB_PAIRED_HISTORICAL_PRICE_EVIDENCE_REQUIRED", out["promotion_blockers"])
        self.assertIn("CFB_FROZEN_PROMOTION_POLICY_REQUIRED", out["promotion_blockers"])
        self.assertFalse(out["promoted"])
        self.assertEqual(len(out["report_sha256"]), 64)

    def test_train_holdout_game_overlap_fails_closed(self):
        with self.assertRaisesRegex(CFBHoldoutEvidenceError, "TRAIN_HOLDOUT_GAME_OVERLAP"):
            analyze([row("t1")])

    def test_holdout_season_must_follow_all_train_seasons(self):
        with self.assertRaisesRegex(CFBHoldoutEvidenceError, "HOLDOUT_NOT_STRICTLY_FORWARD"):
            analyze([row(season=2023)])

    def test_missing_weather_provenance_fails_closed(self):
        bad = row(); bad["weather_evidence_class"] = ""
        with self.assertRaisesRegex(CFBHoldoutEvidenceError, "PREGAME_WEATHER_EVIDENCE_REQUIRED"):
            analyze([bad])

    def test_seed_and_paths_are_required(self):
        bad = row(); bad["seed"] = None
        with self.assertRaisesRegex(CFBHoldoutEvidenceError, "EXPLICIT_INTEGER_SEED_REQUIRED"):
            analyze([bad])
        bad = row(); bad["n_paths"] = 0
        with self.assertRaisesRegex(CFBHoldoutEvidenceError, "N_PATHS_INVALID"):
            analyze([bad])

    def test_market_data_inside_predictive_features_fails_closed(self):
        bad = row(); bad["predictive_features"]["home_team_spread"] = -3.5
        with self.assertRaisesRegex(CFBHoldoutEvidenceError, "MARKET_DATA_PROHIBITED"):
            analyze([bad])

    def test_default_and_injected_lines_are_rejected_from_benchmark_metrics(self):
        out = analyze([row("a", odds_source="default"), row("b", odds_source="injected")])
        self.assertEqual(out["spread"]["settled_n"], 0)
        self.assertEqual(out["total"]["settled_n"], 0)
        self.assertEqual(out["benchmark_excluded_n"], 2)
        self.assertEqual(
            set(out["benchmark_exclusion_reasons"].values()),
            {"CFB_BENCHMARK_ODDS_SOURCE_UNVERIFIED"},
        )

    def test_spread_and_total_pushes_are_not_in_win_rate_denominator(self):
        push = row()
        push["home_score"] = 27
        push["away_score"] = 24
        push["benchmark"]["home_team_spread"] = -3.0
        push["benchmark"]["over_under"] = 51.0
        out = analyze([push])
        self.assertEqual(out["spread"]["push_n"], 1)
        self.assertEqual(out["spread"]["settled_n"], 0)
        self.assertIsNone(out["spread"]["decision_accuracy"])
        self.assertEqual(out["total"]["push_n"], 1)
        self.assertEqual(out["total"]["settled_n"], 0)
        self.assertIsNone(out["total"]["decision_accuracy"])

    def test_identical_inputs_are_content_addressed_deterministically(self):
        rows = [row("g2"), row("g1")]
        a = analyze(rows)
        b = analyze(copy.deepcopy(rows))
        self.assertEqual(a, b)
        self.assertEqual(a["report_sha256"], b["report_sha256"])

    def test_paired_prices_do_not_auto_promote(self):
        out = analyze([row()], paired_historical_price_evidence_complete=True)
        self.assertNotIn("CFB_PAIRED_HISTORICAL_PRICE_EVIDENCE_REQUIRED", out["promotion_blockers"])
        self.assertIn("CFB_FROZEN_PROMOTION_POLICY_REQUIRED", out["promotion_blockers"])
        self.assertEqual(out["promotion_state"], "READY_FOR_FROZEN_POLICY")
        self.assertFalse(out["promoted"])


if __name__ == "__main__":
    unittest.main()
