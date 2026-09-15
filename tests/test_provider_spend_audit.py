from pathlib import Path
import unittest


class ProviderSpendAuditTests(unittest.TestCase):
    def test_spend_audit_preserves_unknown_attribution(self):
        text = Path("docs/market_provider_spend_audit_20260915.md").read_text()
        self.assertIn("PARTIALLY_PROVEN", text)
        self.assertIn("Which workflow/account operation consumed", text)
        self.assertIn("plausible consumer", text)
        self.assertIn("remains an inference", text)
        self.assertIn("MUST NOT be estimated", text)


if __name__ == "__main__":
    unittest.main()
