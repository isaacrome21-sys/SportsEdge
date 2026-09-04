from __future__ import annotations

import unittest

from sportsedge.research.betting_uncertainty import selected_betting_bootstrap
from sportsedge.research.multi_market_backtest import ResearchBacktestError


def _row(*, season: int, i: int, outcome: int | None, clv: float = 0.5):
    return {
        "sport": "MLB",
        "market": "MONEYLINE",
        "event_id": f"{season}-{i}",
        "season": season,
        "feature_asof_ts": f"{season}-06-01T10:00:00+00:00",
        "decision_ts": f"{season}-06-01T11:00:00+00:00",
        "event_start_ts": f"{season}-06-01T12:00:00+00:00",
        "outcome": outcome,
        "model_p": 0.55,
        "benchmark_p": 0.50,
        "offered_decimal": 2.0,
        "clv_pct": clv,
        "selected": True,
    }


class BettingUncertaintyTests(unittest.TestCase):
    def test_deterministic_bootstrap(self):
        rows = []
        for season in (2022, 2023, 2024, 2025):
            for i in range(10):
                rows.append(_row(season=season, i=i, outcome=1 if i < 6 else 0))
        first = selected_betting_bootstrap(rows, reps=100, seed=19)
        second = selected_betting_bootstrap(rows, reps=100, seed=19)
        self.assertEqual(first, second)
        self.assertAlmostEqual(first["roi"], 0.20, places=12)
        self.assertAlmostEqual(first["avg_clv_pct"], 0.5, places=12)
        self.assertIsNotNone(first["roi_ci95"])
        self.assertIsNotNone(first["avg_clv_pct_ci95"])

    def test_push_is_zero_pnl(self):
        rows = [
            _row(season=2024, i=1, outcome=1),
            _row(season=2024, i=2, outcome=None),
            _row(season=2025, i=1, outcome=0),
            _row(season=2025, i=2, outcome=None),
        ]
        result = selected_betting_bootstrap(rows, reps=20, seed=1)
        self.assertEqual(result["push_void_n"], 2)
        self.assertAlmostEqual(result["profit_units"], 0.0, places=12)
        self.assertAlmostEqual(result["roi"], 0.0, places=12)

    def test_requires_multiple_seasons(self):
        rows = [_row(season=2025, i=i, outcome=i % 2) for i in range(4)]
        with self.assertRaisesRegex(ResearchBacktestError, "MULTIPLE_SEASONS"):
            selected_betting_bootstrap(rows, reps=10)


if __name__ == "__main__":
    unittest.main()
