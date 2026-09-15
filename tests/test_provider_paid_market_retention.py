import json
from pathlib import Path
import unittest


class ProviderPaidMarketRetentionTests(unittest.TestCase):
    def test_extended_markets_stay_metered(self):
        rows = {x["consumer"]: x for x in json.loads(Path("config/provider_consumer_registry_v1.json").read_text())["consumers"]}
        row = rows["MLB_RUN_IT_EXTENDED_MARKETS"]
        self.assertEqual(row["preferred_provider"], "THE_ODDS_API")
        self.assertEqual(row["migration_state"], "NO_ELIGIBLE_ESPN_SUBSTITUTION")
        self.assertIn("PLAYER_PROPS", row["markets"])
        self.assertIn("NRFI", row["markets"])
        self.assertIn("YRFI", row["markets"])


if __name__ == "__main__":
    unittest.main()
