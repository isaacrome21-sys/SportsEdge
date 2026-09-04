from __future__ import annotations

import unittest

from sportsedge.research.multi_market_backtest import (
    ResearchBacktestError,
    canonicalize_rows,
    completed_season_walkforward,
    paired_market_bootstrap,
    summarize_binary_market,
)


def _row(*, season: int, i: int, p: float, y: int | None, benchmark: float = 0.50, selected: bool = True):
    return {
        "sport": "NFL",
        "market": "SPREAD",
        "event_id": f"{season}-{i}",
        "season": season,
        "feature_asof_ts": f"{season}-09-01T10:00:00+00:00",
        "decision_ts": f"{season}-09-01T11:00:00+00:00",
        "event_start_ts": f"{season}-09-01T12:00:00+00:00",
        "outcome": y,
        "model_p": p,
        "benchmark_p": benchmark,
        "offered_decimal": 1.91,
        "clv_pct": 0.4,
        "selected": selected,
    }


class CrossSportBacktestTests(unittest.TestCase):
    def test_rejects_post_decision_feature(self):
        row = _row(season=2025, i=1, p=0.55, y=1)
        row["feature_asof_ts"] = "2025-09-01T11:30:00+00:00"
        with self.assertRaisesRegex(ResearchBacktestError, "FEATURE_AFTER_DECISION"):
            canonicalize_rows([row])

    def test_rejects_mixed_market_batch(self):
        a = _row(season=2025, i=1, p=0.55, y=1)
        b = _row(season=2025, i=2, p=0.45, y=0)
        b["market"] = "TOTAL"
        with self.assertRaisesRegex(ResearchBacktestError, "MIXED_SPORT_OR_MARKET"):
            canonicalize_rows([a, b])

    def test_summary_and_roi_are_settlement_aware(self):
        rows = [
            _row(season=2024, i=1, p=0.60, y=1),
            _row(season=2024, i=2, p=0.40, y=0),
            _row(season=2024, i=3, p=0.50, y=None),
        ]
        summary = summarize_binary_market(rows)
        self.assertEqual(summary["n_binary"], 2)
        self.assertEqual(summary["n_push_or_void"], 1)
        self.assertEqual(summary["bet_n"], 3)
        self.assertAlmostEqual(summary["bet_profit_units"], -0.09, places=12)
        self.assertAlmostEqual(summary["bet_roi"], -0.03, places=12)

    def test_walkforward_never_uses_future_season(self):
        rows = []
        for season in range(2020, 2026):
            for i in range(2):
                rows.append(_row(season=season, i=i, p=0.55, y=i % 2))
        folds = completed_season_walkforward(rows, min_train_seasons=3)
        self.assertEqual(folds[0]["test_season"], 2023)
        for fold in folds:
            self.assertTrue(all(season < fold["test_season"] for season in fold["train_seasons"]))

    def test_paired_bootstrap_is_deterministic_and_negative_is_better(self):
        rows = []
        for season in (2022, 2023, 2024, 2025):
            for i in range(40):
                y = i % 2
                p = 0.70 if y else 0.30
                rows.append(_row(season=season, i=i, p=p, y=y, benchmark=0.50))
        first = paired_market_bootstrap(rows, reps=100, seed=7)
        second = paired_market_bootstrap(rows, reps=100, seed=7)
        self.assertEqual(first, second)
        self.assertLess(first["brier_delta_model_minus_benchmark"], 0)
        self.assertLess(first["log_loss_delta_model_minus_benchmark"], 0)
        self.assertLess(first["brier_delta_ci95"][1], 0)
        self.assertLess(first["log_loss_delta_ci95"][1], 0)


if __name__ == "__main__":
    unittest.main()
