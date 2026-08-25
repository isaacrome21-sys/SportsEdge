import unittest

from sportsedge.first_home_run_book_policy import (
    FIRST_HOME_RUN_NO_HR_RULE,
    no_hr_result,
    normalized_no_hr_policy,
    normalized_no_hr_policy_from_record,
)


class FirstHomeRunBookPolicyTests(unittest.TestCase):
    def test_metadata_only_fails_closed(self):
        self.assertIsNone(normalized_no_hr_policy_from_record({"status": "VALIDATED"}))

    def test_event_false_policy_is_side_complete(self):
        record = {"normalized_policy": {"no_home_run": {"YES": "loss", "NO": "win"}}}
        self.assertEqual(normalized_no_hr_policy_from_record(record), {"YES": "LOSS", "NO": "WIN"})

    def test_void_all_policy_is_side_complete(self):
        record = {"normalized_policy": {"no_home_run": {"YES": "VOID", "NO": "VOID"}}}
        self.assertEqual(normalized_no_hr_policy_from_record(record), {"YES": "VOID", "NO": "VOID"})

    def test_mixed_or_contradictory_policy_fails_closed(self):
        for no_hr in (
            {"YES": "LOSS", "NO": "VOID"},
            {"YES": "WIN", "NO": "LOSS"},
            {"YES": "LOSS"},
        ):
            with self.subTest(no_hr=no_hr):
                self.assertIsNone(normalized_no_hr_policy_from_record({"normalized_policy": {"no_home_run": no_hr}}))

    def test_evidence_extraction_is_rule_key_specific(self):
        evidence = {
            FIRST_HOME_RUN_NO_HR_RULE: {
                "normalized_policy": {"no_home_run": {"YES": "LOSS", "NO": "WIN"}}
            }
        }
        policy = normalized_no_hr_policy(evidence)
        self.assertEqual(no_hr_result(policy, "YES"), "LOSS")
        self.assertEqual(no_hr_result(policy, "NO"), "WIN")
        self.assertIsNone(no_hr_result(policy, "OVER"))


if __name__ == "__main__":
    unittest.main()
