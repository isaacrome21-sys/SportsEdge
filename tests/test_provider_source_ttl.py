import json
from pathlib import Path
import unittest


class ProviderSourceTTLTests(unittest.TestCase):
    def test_espn_ttl_is_declared_source_routing_property(self):
        contract = json.loads(Path("config/market_provider_contract_v1.json").read_text())
        espn = next(x for x in contract["rules"] if x["provider"] == "ESPN_SCOREBOARD")
        self.assertEqual(espn["freshness"]["basis"], "SOURCE_NATIVE_TIMESTAMP")
        self.assertEqual(espn["freshness"]["ttl_seconds"], 60)
        ledger = Path("docs/market_provider_migration_20260915.md").read_text()
        self.assertIn("source-routing property, not a replay/evidence-policy TTL", ledger)


if __name__ == "__main__":
    unittest.main()
