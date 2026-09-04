from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from sportsedge.research.calibration_selection import select_calibrator
from sportsedge.research.multi_market_backtest import ResearchBacktestError


BASE = datetime(2024, 9, 1, tzinfo=timezone.utc)


def _rows(n: int = 120):
    rows = []
    for i in range(n):
        high = i % 2 == 0
        j = i // 2
        p = 0.80 if high else 0.20
        outcome = 1 if (j % 5 < (3 if high else 2)) else 0
        start = BASE + timedelta(hours=4 * i)
        rows.append({
            "sport": "NFL",
            "market": "MONEYLINE",
            "event_id": f"g{i}",
            "season": 2024,
            "feature_asof_ts": start - timedelta(hours=3),
            "decision_ts": start - timedelta(hours=2),
            "event_start_ts": start,
            "outcome": outcome,
            "model_p": p,
        })
    return rows


class CalibrationSelectionTests(unittest.TestCase):
    def test_overconfident_probabilities_choose_nonidentity_when_it_improves(self):
        calibrator = select_calibrator(_rows())
        self.assertIn(calibrator.method, {"PLATT", "ISOTONIC"})
        chosen = calibrator.selection_scores[calibrator.method]
        identity = calibrator.selection_scores["IDENTITY"]
        self.assertLessEqual(chosen["brier"], identity["brier"] + 1e-6)
        self.assertLessEqual(chosen["log_loss"], identity["log_loss"] + 1e-6)
        self.assertGreater(calibrator.predict(0.20), 0.20)
        self.assertLess(calibrator.predict(0.80), 0.80)

    def test_selection_is_deterministic(self):
        first = select_calibrator(_rows())
        second = select_calibrator(_rows())
        self.assertEqual(first, second)

    def test_small_calibration_fold_fails_closed(self):
        with self.assertRaisesRegex(ResearchBacktestError, "INSUFFICIENT"):
            select_calibrator(_rows(40), minimum_rows=90)


if __name__ == "__main__":
    unittest.main()
