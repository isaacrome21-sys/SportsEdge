from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOLD = ROOT / ".github" / "workflows" / "ev-tracker.yml"
CLOSE = ROOT / ".github" / "workflows" / "ev-close-v2-runtime.yml"


class EVTrackerWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hold = HOLD.read_text(encoding="utf-8")
        cls.close = CLOSE.read_text(encoding="utf-8")

    def test_intake_hold_remains_quiesced(self):
        self.assertIn("EV_TRACKER_DIRECT_MAIN_WRITER_QUIESCED", self.hold)
        self.assertNotIn("schedule:", self.hold)
        self.assertNotIn("ev_tracker.py", self.hold)
        self.assertIn("contents: read", self.hold)

    def test_close_runner_is_scheduled_without_new_bet_intake(self):
        self.assertIn('cron: "*/30 * * * *"', self.close)
        self.assertIn("python scripts/ev_tracker.py close", self.close)
        self.assertNotIn("types: [opened, edited]", self.close)
        self.assertNotIn("log-bet:", self.close)

    def test_persistence_uses_data_branch_not_protected_main(self):
        self.assertIn("runtime/ev-tracker-v2", self.close)
        self.assertIn("git push origin HEAD:data", self.close)
        self.assertNotIn("git push origin HEAD:main", self.close)

    def test_existing_ledger_rows_are_hash_guarded_and_create_only(self):
        for token in ("IMMUTABLE_LEDGER_DRIFT", "PERSIST_CONFLICT", "ev-before.json", "ev-new-files.txt"):
            self.assertIn(token, self.close)

    def test_runtime_health_explicitly_has_zero_authority(self):
        for token in (
            "'intake_enabled':False",
            "'backfill_enabled':False",
            "'evidence_authority':False",
            "'model_p_authority':False",
            "'truth_gate_authority':False",
            "'promotion_authority':False",
            "'official_authority':False",
        ):
            self.assertIn(token, self.close)


if __name__ == "__main__":
    unittest.main()
