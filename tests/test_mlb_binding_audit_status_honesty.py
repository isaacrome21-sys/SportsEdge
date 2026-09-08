import unittest

from sportsedge.mlb_market_binding_v13 import audit_status


class BindingAuditStatusHonestyTests(unittest.TestCase):
    def test_no_market_self_reports_pass_from_structure(self):
        for market in ("MONEYLINE", "RUN_LINE", "TOTALS"):
            self.assertEqual(audit_status(market), "WIRED_UNVERIFIED")

    def test_team_totals_is_not_claimed_wired(self):
        self.assertEqual(audit_status("TEAM_TOTALS"), "UNAUDITABLE_IMPLICIT")


if __name__ == "__main__":
    unittest.main()
