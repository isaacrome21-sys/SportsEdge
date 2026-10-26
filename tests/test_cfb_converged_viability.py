"""Adversarial pre-freeze successor tests; unittest-discovery compatible."""
from __future__ import annotations

import importlib.util
import inspect
import json
import math
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from sportsedge.sports.cfb import converged_successor as candidate

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "evaluate_cfb_converged_viability",
    ROOT / "scripts/evaluate_cfb_converged_viability.py",
)
screening = importlib.util.module_from_spec(spec)
spec.loader.exec_module(screening)


def _game(gid, day, home=1, away=2, week=5, neutral=False,
          hp=30, ap=20, hdiv="fbs", adiv="fbs"):
    return candidate.Game(
        game_id=gid, season=2024, week=week,
        instant=datetime(2024, 9, 1, 12, tzinfo=UTC) + timedelta(days=day),
        home_id=home, away_id=away, home_points=hp, away_points=ap,
        neutral_site=neutral, home_division=hdiv, away_division=adiv,
    )


def _row(season, game_id, raw, close, actual):
    return {"season": season, "game_id": game_id, "raw_prediction": raw,
            "market_close": close, "actual": actual}


class CfbConvergedViabilityTests(unittest.TestCase):
    def test_prior_result_embargo_blocks_same_day_leak(self):
        games = [_game(1, 0, hp=50, ap=0), _game(2, 0.99),
                 _game(3, 1), _game(4, 2), _game(5, 3), _game(6, 4)]
        projections = candidate.project_season(games)
        self.assertNotIn(2, [p.game_id for p in projections])
        self.assertEqual([p.game_id for p in projections], [4, 5, 6])
        self.assertEqual(projections[-1].training_games_available, 5)

    def test_neutral_site_removes_exact_home_advantage(self):
        prior = [_game(i, i - 1, hp=30 + i, ap=20) for i in range(1, 5)]
        games = prior + [_game(11, 5, neutral=True), _game(12, 5, neutral=False)]
        pred = {p.game_id: p for p in candidate.project_season(games)}
        self.assertTrue({11, 12}.issubset(pred))
        self.assertAlmostEqual(
            pred[12].raw_margin - pred[11].raw_margin, candidate.HFA_POINTS)

    def test_fbs_fcs_mismatch_not_train_or_project(self):
        prior = [_game(1, 0), _game(2, 1), _game(3, 2, adiv="fcs"),
                 _game(4, 3)]
        games = prior + [_game(5, 4, adiv="fcs"), _game(6, 5)]
        predictions = candidate.project_season(games)
        self.assertNotIn(5, [p.game_id for p in predictions])
        self.assertEqual([p.game_id for p in predictions], [6])
        self.assertEqual(predictions[0].training_games_available, 3)

    def test_chronology_and_duplicates_refuse(self):
        with self.assertRaisesRegex(ValueError, "NONCHRONOLOGICAL"):
            candidate.project_season([_game(1, 2), _game(2, 1)])
        with self.assertRaisesRegex(ValueError, "DUPLICATE_RESULT_GAME_ID"):
            candidate.project_season([_game(1, 0), _game(1, 1)])

    def test_missing_neutral_and_naive_clock_refuse(self):
        with self.assertRaisesRegex(ValueError, "NEUTRAL_SITE_UNKNOWN"):
            _game(1, 0, neutral=None)
        with self.assertRaisesRegex(ValueError, "KICKOFF_CLOCK_MISSING"):
            candidate.Game(
                1, 2024, 5, datetime(2024, 9, 1), 1, 2,
                31, 17, False, "fbs", "fbs",
            )

    def test_fixed_point_converges_and_margin_is_capped(self):
        games = [_game(i, i, hp=80, ap=0) for i in range(1, 6)]
        games.append(_game(10, 7))
        projections = candidate.project_season(games)
        self.assertEqual(projections[-1].game_id, 10)
        self.assertLessEqual(abs(projections[-1].raw_margin), candidate.MAX_RAW_MARGIN)
        self.assertLess(projections[-1].iterations, candidate.ITERATIONS)

    def test_proposed_market_cap_is_not_a_screen_input(self):
        self.assertEqual(list(inspect.signature(candidate.proposed_market_anchor).parameters),
                         ["raw", "observed_entry_line"])
        self.assertEqual(candidate.proposed_market_anchor(20, 0), 4)
        self.assertEqual(candidate.proposed_market_anchor(-20, 0), -4)
        with self.assertRaisesRegex(ValueError, "NONFINITE_ANCHOR"):
            candidate.proposed_market_anchor(math.nan, 0)
        self.assertEqual(screening._slope([0, 10, 20], [0, 2, 4]), 0.2)

    def test_beta_signs_and_accuracy_gate_jointly_required(self):
        # Each season contributes 120 paired events with nontrivial x variance.
        rows = [_row(s, 10000 * s + i, i % 5 - 2, 0,
                     (i % 5 - 2) * 0.5)
                for s in screening.DESIGN_SEASONS for i in range(120)]
        result = screening.screen(rows)
        self.assertTrue(result["checks"]["beta"])
        self.assertTrue(result["checks"]["season_signs"])
        self.assertTrue(result["checks"]["coverage"])
        self.assertEqual(result["status"], "PASSED_PRE_FREEZE_SCREEN_RESEARCH_ONLY")
        # A very inaccurate model must fail even with a high positive slope.
        worse = [_row(r["season"], r["game_id"],
                      r["raw_prediction"] + 100, 0, r["actual"]) for r in rows]
        self.assertFalse(screening.screen(worse)["checks"]["accuracy"])

    def test_one_positive_season_fails(self):
        rows = [_row(s, 10000 * s + i, i % 5 - 2, 0,
                     (i % 5 - 2) * (0.4 if s == 2023 else -0.4))
                for s in screening.DESIGN_SEASONS for i in range(120)]
        result = screening.screen(rows)
        self.assertEqual(result["positive_seasons"], 1)
        self.assertEqual(result["status"], "FAILED_NO_VIABLE_SCORE_ONLY_CONSTRUCTION")

    def test_sparse_and_constant_x_refuse(self):
        sparse = [_row(2023, i, 1, 0, 1) for i in range(150)]
        result = screening.screen(sparse)
        self.assertFalse(result["checks"]["coverage"])
        self.assertIsNone(result["pooled"]["beta"])
        self.assertEqual(result["status"], "INSUFFICIENT_SCOREABLE_DESIGN_SEASONS")

    def test_strict_boolean_parse(self):
        for value in (None, "", 0, 1, float("nan"), "unknown"):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, "REQUIRED_BOOLEAN_UNKNOWN"
            ):
                screening._bool(value)
        self.assertTrue(screening._bool("TRUE"))
        self.assertFalse(screening._bool("False"))

    def test_missing_source_columns_abort_before_report_written(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            pd.DataFrame({"game_id": [1]}).to_csv(data / "sdv_cfb_results_all.csv", index=False)
            pd.DataFrame({"game_id": [1]}).to_csv(data / "sdv_cfb_closes_all.csv", index=False)
            with self.assertRaisesRegex(ValueError, "SOURCE_SCHEMA_MISSING"):
                screening.evaluate(data)

    def test_duplicate_close_abort_and_no_partial_verdict(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            pd.DataFrame(columns=[
                "game_id", "season", "week", "start_date", "neutral_site",
                "home_id", "away_id", "home_division", "away_division",
                "home_points", "away_points",
            ]).to_csv(data / "sdv_cfb_results_all.csv", index=False)
            pd.DataFrame({
                "game_id": [1, 1], "season": [2023, 2023],
                "home_id": [1, 1], "away_id": [2, 2],
                "neutral_site": [False, False],
                "home_team_spread": [-3, -3], "over_under": [50, 50],
                "spread_scoreable": [True, True], "total_scoreable": [True, True],
                "home_division": ["fbs", "fbs"],
                "away_division": ["fbs", "fbs"],
            }).to_csv(data / "sdv_cfb_closes_all.csv", index=False)
            with self.assertRaisesRegex(ValueError, "DUPLICATE_GAME_ID"):
                screening.evaluate(data)

    def test_authority_fields_remain_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            cols = ["game_id", "season", "week", "start_date", "neutral_site",
                    "home_id", "away_id", "home_division", "away_division",
                    "home_points", "away_points"]
            pd.DataFrame([dict(zip(cols, [100+s, s, 1, f"{s}-09-01T12:00:00Z",
                                               False, 1, 2, "fbs", "fbs", 7, 3]))
                          for s in screening.DESIGN_SEASONS]).to_csv(
                              data / "sdv_cfb_results_all.csv", index=False)
            pd.DataFrame(columns=[
                "game_id", "season", "home_id", "away_id", "neutral_site",
                "home_team_spread", "over_under", "spread_scoreable",
                "total_scoreable", "home_division", "away_division",
            ]).to_csv(data / "sdv_cfb_closes_all.csv", index=False)
            (data / "provenance.json").write_text(
                json.dumps({"retrieved_at_utc": "synthetic", "files": {}}))
            report, rows = screening.evaluate(data)
            self.assertEqual(rows, [])
            self.assertFalse(report["freeze_authorized"])
            self.assertFalse(report["model_p_authority"])
            self.assertFalse(report["verified_clv"])
            self.assertFalse(report["production_eligible"])
            self.assertEqual(report["cfb_production_weight"], 0)
            self.assertEqual(report["backup_qb_signal"],
                             "NOT_EVALUATED_NO_HISTORICAL_ASOF_QB_RECEIPTS")
            self.assertEqual(report["disposition"],
                             "NO_VIABLE_SCORE_ONLY_CONSTRUCTION_IN_THIS_FIXED_SCREEN")


if __name__ == "__main__":
    unittest.main()
