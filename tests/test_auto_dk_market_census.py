"""Lane 9: requested market families cannot masquerade as a full DK scan.

Purely offline: no credentials, sportsbook requests, prices or model results.
"""
import unittest
from pathlib import Path
import subprocess
import sys

from scripts.audit_auto_dk_market_census import REQUIRED_FAMILIES, audit


class AutoDkMarketCensusTests(unittest.TestCase):
    def test_live_scope_reports_exact_missing_families(self):
        report = audit()
        self.assertEqual(report["status"], "INCOMPLETE")
        self.assertEqual(report["required_family_count"], 40)
        self.assertEqual(report["families_requested_but_unverified"], 12)
        self.assertEqual(report["families_not_requested"], 28)
        self.assertEqual(report["base_market_keys_requested"], ["h2h", "spreads", "totals"])
        self.assertEqual(report["sport_keys_requested"], ["CFB", "MLB", "NBA", "NFL"])

    def test_nhl_has_no_automatic_capture_at_all(self):
        nhl = audit()["sports"]["NHL"]
        self.assertFalse(nhl["sport_configured"])
        self.assertEqual(nhl["requested_unverified"], 0)
        self.assertEqual(nhl["not_requested"], len(REQUIRED_FAMILIES["NHL"]))
        self.assertTrue(all(row["status"] == "SPORT_NOT_CONFIGURED"
                            for row in nhl["families"]))

    def test_periods_alternates_team_totals_props_not_counted_as_base_lines(self):
        report = audit()
        for sport in ("NFL", "CFB", "NBA"):
            by_family = {row["family"]: row for row in report["sports"][sport]["families"]}
            for family in ("alternate_lines", "halves", "quarters",
                           "team_totals", "player_props"):
                self.assertEqual(by_family[family]["status"], "FAMILY_NOT_REQUESTED")
        mlb = {row["family"]: row for row in report["sports"]["MLB"]["families"]}
        for family in ("first_five", "first_inning", "batter_props", "pitcher_props"):
            self.assertEqual(mlb[family]["status"], "FAMILY_NOT_REQUESTED")

    def test_requested_does_not_mean_quote_or_model_verified(self):
        report = audit()
        for sport in report["sports"].values():
            for row in sport["families"]:
                self.assertFalse(row["quote_verified"])
                self.assertFalse(row["model_validated"])
        for key in ("provider_catalog_authenticated", "exact_dk_market_census_complete",
                    "full_board_coverage_verified", "pricing_validated", "play_authority"):
            self.assertFalse(report[key])

    def test_hypothetical_nhl_enable_only_adds_unverified_base_requests(self):
        sports = {"NFL": "americanfootball_nfl", "CFB": "americanfootball_ncaaf",
                  "MLB": "baseball_mlb", "NBA": "basketball_nba",
                  "NHL": "icehockey_nhl"}
        report = audit(sports=sports)
        self.assertEqual(report["sports"]["NHL"]["requested_unverified"], 3)
        self.assertEqual(report["status"], "INCOMPLETE")
        self.assertFalse(report["full_board_coverage_verified"])
        self.assertFalse(report["play_authority"])

    def test_census_cli_imports_repository_from_script_directory(self):
        root = Path(__file__).resolve().parents[1]
        proc = subprocess.run([sys.executable, "scripts/audit_auto_dk_market_census.py"],
                              cwd=root, text=True, capture_output=True, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(__import__("json").loads(proc.stdout)["status"], "INCOMPLETE")

    def test_missing_base_market_key_is_a_gap_not_an_inferred_price(self):
        report = audit(markets={"h2h"})
        for sport in ("NFL", "CFB", "MLB", "NBA"):
            self.assertEqual(report["sports"][sport]["requested_unverified"], 1)
        self.assertEqual(report["families_requested_but_unverified"], 4)


if __name__ == "__main__":
    unittest.main()
