from __future__ import annotations

import unittest

from sportsedge.mlb_coverage import MLBCoverageError, MLBCoverageItem, MLBCoverageReport, build_mlb_coverage_report


class MLBCoverageTests(unittest.TestCase):
    def test_expected_contracts_are_all_accounted(self):
        expected = (("g1", "V7_GAME"), ("g2", "V7_GAME"), ("g2", "PITCHER_JOINT"))
        rows = [
            {"game_id": "g1", "market_family": "V7_GAME", "status": "PRICED"},
            {"game_id": "g2", "market_family": "PITCHER_JOINT", "status": "BLOCKED", "reason": "STARTER_UNCONFIRMED"},
        ]
        report = build_mlb_coverage_report(expected_contracts=expected, result_rows=rows)
        states = {(x.game_id, x.market_family): x.status for x in report.items}
        self.assertEqual(states[("g1", "V7_GAME")], "PRICED")
        self.assertEqual(states[("g2", "V7_GAME")], "UNAVAILABLE")
        self.assertEqual(states[("g2", "PITCHER_JOINT")], "BLOCKED")
        self.assertEqual(report.status_counts(), {"PRICED": 1, "BLOCKED": 1, "UNAVAILABLE": 1})
        self.assertAlmostEqual(report.coverage_rate, 1 / 3)

    def test_missing_expected_item_fails_closed(self):
        report = MLBCoverageReport(
            expected_contracts=(("g1", "V7_GAME"), ("g2", "V7_GAME")),
            items=(MLBCoverageItem("g1", "V7_GAME", "PRICED"),),
        )
        with self.assertRaisesRegex(MLBCoverageError, "SILENT_DROP"):
            report.validate()


if __name__ == "__main__":
    unittest.main()
