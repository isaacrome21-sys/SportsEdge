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

    def test_same_kickoff_cohort_stays_on_selection_side(self):
        rows = _rows()
        for i in range(78, 83):
            for key in ("event_start_ts", "decision_ts", "feature_asof_ts"):
                rows[i][key] = rows[78][key]
        result = select_calibrator(rows)
        self.assertEqual((result.fit_n, result.selection_n), (78, 42))
        self.assertEqual(result, select_calibrator(reversed(rows)))

    def test_repeated_event_snapshots_cannot_cross_split(self):
        rows = _rows()
        for i in range(78, 83):
            rows[i] = {**rows[78], "decision_ts": rows[78]["decision_ts"] + timedelta(minutes=i - 78)}
        result = select_calibrator(rows)
        self.assertEqual((result.fit_n, result.selection_n), (78, 42))

    def test_single_kickoff_cohort_cannot_form_chronological_split(self):
        rows = _rows()
        for row in rows:
            for key in ("event_start_ts", "decision_ts", "feature_asof_ts"):
                row[key] = rows[0][key]
        with self.assertRaisesRegex(ResearchBacktestError, "SPLIT_TOO_SMALL"):
            select_calibrator(rows)

    def test_conflicting_clock_for_same_event_refused(self):
        rows = _rows()
        rows[80]["event_id"] = rows[79]["event_id"]
        with self.assertRaisesRegex(ResearchBacktestError, "EVENT_CLOCK_CONFLICT"):
            select_calibrator(rows)

    def test_selection_decision_before_fit_game_refused(self):
        rows = _rows()
        rows[80]["decision_ts"] = rows[79]["event_start_ts"]
        rows[80]["feature_asof_ts"] = rows[80]["decision_ts"]
        with self.assertRaisesRegex(ResearchBacktestError, "FIT_EVENT_NOT_BEFORE_SELECTION_DECISION"):
            select_calibrator(rows)


if __name__ == "__main__":
    unittest.main()
