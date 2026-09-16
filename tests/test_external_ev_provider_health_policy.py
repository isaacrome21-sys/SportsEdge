import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "external_ev_provider_health_policy_v1.json"
WORKFLOW = ROOT / ".github" / "workflows" / "ev-provider-health.yml"


class ExternalEVProviderHealthPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = json.loads(POLICY.read_text(encoding="utf-8"))
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_threshold_starts_unfrozen_and_observe_only(self):
        self.assertEqual(self.policy["mode"], "OBSERVE_ONLY")
        self.assertEqual(self.policy["threshold"]["status"], "UNFROZEN")
        self.assertFalse(self.policy["threshold"]["automated_suspension_enabled"])

    def test_inflight_close_obligation_cannot_be_forgiven(self):
        c = self.policy["admission_contract"]
        self.assertTrue(c["policy_at_admission_is_immutable"])
        self.assertTrue(c["active_admission_close_obligation_survives_later_suspension"])
        self.assertEqual(c["missing_close_denominator_label"], "MISSING_CLOSE")
        self.assertTrue(c["existing_v2_misses_remain_in_denominator"])
        self.assertFalse(c["backfill_existing_misses"])

    def test_suspension_is_prospective_and_cannot_backdate(self):
        c = self.policy["admission_contract"]
        self.assertTrue(c["suspension_is_prospective_only"])
        self.assertTrue(c["effective_time_equals_declared_at"])
        self.assertTrue(c["backdating_forbidden"])

    def test_probe_is_independent_and_persists_outside_main(self):
        self.assertTrue(self.policy["probe"]["independent_of_bet_stream"])
        self.assertIn('cron: "17 * * * *"', self.workflow)
        self.assertIn("ev_provider_health_probe.py", self.workflow)
        self.assertIn("runtime/ev-tracker-v2/provider-health", self.workflow)
        self.assertIn("git push origin HEAD:data", self.workflow)
        self.assertNotIn("git push origin HEAD:main", self.workflow)


if __name__ == "__main__":
    unittest.main()
