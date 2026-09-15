import json
from pathlib import Path
import unittest


class ProviderBranchScopeTests(unittest.TestCase):
    def test_contract_has_no_predictive_authority(self):
        c = json.loads(Path("config/market_provider_contract_v1.json").read_text())
        self.assertFalse(c["promotion_authority"])
        self.assertFalse(c["model_p_authority"])
        self.assertEqual(c["authority"], "ROUTING_AND_PROVENANCE_ONLY")

    def test_spend_audit_does_not_claim_attribution(self):
        text = Path("docs/market_provider_spend_audit_20260915.md").read_text()
        self.assertIn("PARTIALLY_PROVEN", text)
        self.assertIn("Not proven", text)
        self.assertIn("Which workflow/account operation consumed", text)


if __name__ == "__main__":
    unittest.main()
