import unittest

from sportsedge.sports.cfb.oos_validation import CFBOOSValidationError, walk_forward_validate_cfb


class CFBOOSValidationTests(unittest.TestCase):
    def test_requires_multiple_seasons(self):
        with self.assertRaisesRegex(CFBOOSValidationError, "MULTIPLE_SEASONS"):
            walk_forward_validate_cfb([{"season": 2025, "home_score": 21, "away_score": 17}])

    def test_empty_rows_fail_closed(self):
        with self.assertRaisesRegex(CFBOOSValidationError, "ROWS_REQUIRED"):
            walk_forward_validate_cfb([])

    def test_report_cannot_claim_promotion_evidence(self):
        # Full feature-contract fixture coverage lives in the historical/materializer tests;
        # this contract pins the governance defaults independently of numerical fitting.
        from sportsedge.sports.cfb.oos_validation import CFBOOSReport
        report = CFBOOSReport(
            "CFB_WALK_FORWARD_OOS_V1", "RESEARCH_ONLY_NOT_PROMOTION_EVIDENCE", (), 1,
            1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0,
        )
        self.assertFalse(report.promotion_evidence)
        self.assertFalse(report.clv_evidence)
        self.assertFalse(report.roi_evidence)
        self.assertFalse(report.calibration_evidence)


if __name__ == "__main__":
    unittest.main()
