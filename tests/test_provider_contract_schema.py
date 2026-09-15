import json
from pathlib import Path
import unittest


class ProviderContractSchemaTests(unittest.TestCase):
    def test_schema_and_non_silent_rule_are_versioned(self):
        payload = json.loads(Path("config/market_provider_contract_v1.json").read_text())
        self.assertEqual(payload["schema_version"], "MARKET_PROVIDER_CONTRACT_V1")
        self.assertTrue(payload["non_silent_satisfaction"])


if __name__ == "__main__":
    unittest.main()
