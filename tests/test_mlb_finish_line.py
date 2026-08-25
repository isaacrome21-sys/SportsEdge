import unittest

from sportsedge.mlb_finish_line import build_mlb_finish_line


EXPECTED_EXTERNAL = {
    "F5_TEAM_TOTALS",
    "EXTRA_BASE_HITS",
    "HITS_RUNS_STOLEN_BASES",
    "RUNS_RBIS",
    "HITS_STOLEN_BASES",
    "HITS_WALKS_STOLEN_BASES",
    "PITCHER_HITS_WALKS_ER",
    "EITHER_PITCHER_HITS_ALLOWED",
    "EITHER_PITCHER_BB",
    "EITHER_PITCHER_ER",
}


class MLBFinishLineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = build_mlb_finish_line()
        cls.rows = {row["market"]: row for row in cls.report["markets"]}

    def test_complete_catalog_has_no_hidden_code_gap(self):
        self.assertEqual(self.report["market_count"], 38)
        self.assertTrue(self.report["engineering_finish_line_complete"])
        self.assertEqual(self.report["code_missing_markets"], [])
        self.assertEqual(len(self.rows), 38)
        for row in self.rows.values():
            self.assertTrue(row["runtime_engine_present"])
            self.assertTrue(row["deployment_registered"])
            self.assertTrue(row["settlement_interpreter_present"])
            self.assertNotIn("CODE_MISSING", row["blockers"])

    def test_external_provider_blockers_are_explicit_and_exhaustive(self):
        self.assertEqual(set(self.report["external_provider_markets"]), EXPECTED_EXTERNAL)
        for market in EXPECTED_EXTERNAL:
            row = self.rows[market]
            self.assertFalse(row["provider_expected"])
            self.assertEqual(row["acquisition_state"], "EXTERNAL_PROVIDER_REQUIRED")
            self.assertEqual(row["primary_blocker"], "EXTERNAL_PROVIDER_REQUIRED")

    def test_first_home_run_keeps_no_hr_book_policy_blocker(self):
        row = self.rows["FIRST_HOME_RUN"]
        self.assertTrue(row["engineering_code_complete"])
        self.assertEqual(row["primary_blocker"], "BOOK_POLICY_NORMALIZATION_REQUIRED")
        self.assertIn("VALIDATION_EVIDENCE_REQUIRED", row["blockers"])

    def test_either_pitcher_has_code_but_still_requires_external_quotes_and_book_rules(self):
        for market in ("EITHER_PITCHER_HITS_ALLOWED", "EITHER_PITCHER_BB", "EITHER_PITCHER_ER"):
            row = self.rows[market]
            self.assertTrue(row["engineering_code_complete"])
            self.assertIn("BOOK_RULE_VALIDATION_REQUIRED", row["blockers"])
            self.assertIn("EXTERNAL_PROVIDER_REQUIRED", row["blockers"])

    def test_pitcher_record_win_is_candidate_not_evidence_complete(self):
        row = self.rows["PITCHER_RECORD_WIN"]
        self.assertEqual(row["deployment_stage"], "GAME_STATE_CANDIDATE")
        self.assertFalse(row["deployment_eligible"])
        self.assertTrue(row["engineering_code_complete"])
        self.assertIn("VALIDATION_EVIDENCE_REQUIRED", row["blockers"])

    def test_engineering_finish_is_not_misreported_as_evidence_finish(self):
        self.assertFalse(self.report["evidence_finish_line_complete"])
        self.assertEqual(self.report["acceptance_complete_count"], 0)


if __name__ == "__main__":
    unittest.main()
