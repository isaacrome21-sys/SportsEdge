import json
from pathlib import Path
import unittest


class ProviderSpendStatusTests(unittest.TestCase):
    def test_status_does_not_upgrade_spend_attribution(self):
        status = json.loads(Path("docs/provider_abstraction_status.json").read_text())
        self.assertEqual(status["spend_attribution"], "PARTIALLY_PROVEN")


if __name__ == "__main__":
    unittest.main()
