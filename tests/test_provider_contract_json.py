import json
from pathlib import Path
import unittest


class ProviderContractJSONTests(unittest.TestCase):
    def test_espn_contract_is_narrow_and_fail_closed(self):
        payload = json.loads(Path("config/market_provider_contract_v1.json").read_text())
        espn = next(x for x in payload["rules"] if x["provider"] == "ESPN_SCOREBOARD")
        self.assertEqual(set(espn["markets"]), {"MONEYLINE", "RUN_LINE", "TOTALS"})
        self.assertTrue(espn["book_identity"]["required"])
        self.assertFalse(espn["book_identity"]["fallback_satisfies_exact_book_contract"])
        self.assertEqual(espn["freshness"]["ttl_seconds"], 60)
        self.assertTrue(espn["freshness"]["timestamp_required"])
        self.assertIn("PLAYER_PROPS", espn["ineligible_markets"])
        self.assertIn("NRFI", espn["ineligible_markets"])
        self.assertIn("YRFI", espn["ineligible_markets"])


if __name__ == "__main__":
    unittest.main()
