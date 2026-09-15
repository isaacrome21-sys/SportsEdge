import json
from pathlib import Path
import unittest


class ProviderStatusTests(unittest.TestCase):
    def test_pre_pr_status_is_fail_closed(self):
        row = json.loads(Path("docs/provider_abstraction_status.json").read_text())
        self.assertEqual(row["content_state"], "READY_FOR_HOSTED_CI")
        self.assertEqual(row["hosted_ci"], "NOT_YET_RUN_ON_PR_HEAD")
        self.assertEqual(row["spend_attribution"], "PARTIALLY_PROVEN")
        self.assertFalse(row["frozen_nfl_confirmation_changed"])
        self.assertFalse(row["model_p_authority"])
        self.assertFalse(row["official_authority"])


if __name__ == "__main__":
    unittest.main()
