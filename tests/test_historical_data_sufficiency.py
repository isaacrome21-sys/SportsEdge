from __future__ import annotations

import unittest

from sportsedge.research.historical_data_sufficiency import (
    HistoricalDataSufficiencyError,
    grade_market_rows,
)


def _row(season: int, i: int, *, with_quotes: bool = True, with_close: bool = True):
    row = {
        "sport": "NFL",
        "market": "SPREAD",
        "event_id": f"{season}-{i}",
        "season": season,
        "feature_asof_ts": f"{season}-09-01T10:00:00+00:00",
        "decision_ts": f"{season}-09-01T11:00:00+00:00",
        "event_start_ts": f"{season}-09-01T12:00:00+00:00",
        "outcome": i % 2,
        "model_p": 0.52,
        "benchmark_p": 0.50,
    }
    if with_quotes:
        row["offered_decimal"] = 1.91
    if with_close:
        row["close_decimal"] = 1.87
        row["close_ts"] = f"{season}-09-01T11:55:00+00:00"
    return row


class HistoricalDataSufficiencyTests(unittest.TestCase):
    def test_full_evidence_is_ready(self):
        rows = [_row(season, i) for season in (2023, 2024, 2025) for i in range(4)]
        report = grade_market_rows(rows, min_probability_rows=10, min_betting_rows=10, min_seasons=3)
        self.assertEqual(report.probability_validation_status, "READY")
        self.assertEqual(report.betting_backtest_status, "READY")
        self.assertEqual(report.clv_backtest_status, "READY")
        self.assertEqual(report.blockers, ())

    def test_outcomes_without_decision_quotes_are_not_betting_ready(self):
        rows = [_row(season, i, with_quotes=False) for season in (2023, 2024, 2025) for i in range(4)]
        report = grade_market_rows(rows, min_probability_rows=10, min_betting_rows=10, min_seasons=3)
        self.assertEqual(report.probability_validation_status, "READY")
        self.assertEqual(report.betting_backtest_status, "NOT_READY")
        self.assertIn("DECISION_TIME_QUOTES_MISSING_OR_INSUFFICIENT", report.blockers)

    def test_decision_quotes_without_close_are_not_clv_ready(self):
        rows = [_row(season, i, with_close=False) for season in (2023, 2024, 2025) for i in range(4)]
        report = grade_market_rows(rows, min_probability_rows=10, min_betting_rows=10, min_seasons=3)
        self.assertEqual(report.betting_backtest_status, "READY")
        self.assertEqual(report.clv_backtest_status, "NOT_READY")
        self.assertIn("CLOSE_QUOTES_OR_CANONICAL_CLV_MISSING_OR_INSUFFICIENT", report.blockers)

    def test_post_start_decision_breaks_pit_readiness(self):
        rows = [_row(season, i) for season in (2023, 2024, 2025) for i in range(4)]
        for row in rows:
            row["decision_ts"] = row["event_start_ts"]
        report = grade_market_rows(rows, min_probability_rows=10, min_betting_rows=10, min_seasons=3)
        self.assertEqual(report.probability_validation_status, "NOT_READY")
        self.assertIn("PIT_FEATURE_EVIDENCE_MISSING_OR_INSUFFICIENT", report.blockers)

    def test_mixed_market_fails(self):
        rows = [_row(2025, i) for i in range(3)]
        rows[-1]["market"] = "TOTAL"
        with self.assertRaisesRegex(HistoricalDataSufficiencyError, "MIXED"):
            grade_market_rows(rows, min_probability_rows=1, min_betting_rows=1, min_seasons=1)


if __name__ == "__main__":
    unittest.main()
