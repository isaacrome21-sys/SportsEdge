from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ev-tracker.yml"


class EVTrackerWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_close_runner_is_scheduled_but_new_bet_intake_remains_disabled(self):
        self.assertIn('cron: "*/30 * * * *"', self.text)
        self.assertIn("python scripts/ev_tracker.py close", self.text)
        self.assertNotIn("types: [opened, edited]", self.text)
        self.assertNotIn("log-bet:", self.text)

    def test_persistence_uses_data_branch_not_protected_main(self):
        self.assertIn("runtime/ev-tracker-v2", self.text)
        self.assertIn("git push origin HEAD:data", self.text)
        self.assertNotIn("git push origin HEAD:main", self.text)
        self.assertNotIn("git pull --rebase && git push", self.text)

    def test_existing_ledger_rows_are_hash_guarded_and_new_rows_are_create_only(self):
        self.assertIn("IMMUTABLE_LEDGER_DRIFT", self.text)
        self.assertIn("PERSIST_CONFLICT", self.text)
        self.assertIn("ev-before.json", self.text)
        self.assertIn("ev-new-files.txt", self.text)

    def test_runtime_health_explicitly_has_zero_authority(self):
        for field in (
            '"intake_enabled": False',
            '"evidence_authority": False',
            '"model_p_authority": False',
            '"truth_gate_authority": False',
            '"promotion_authority": False',
            '"official_authority": False',
        ):
            self.assertIn(field, self.text)


if __name__ == "__main__":
    unittest.main()
