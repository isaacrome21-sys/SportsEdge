import json
from pathlib import Path
import unittest


class ProviderMigrationNoNFLTests(unittest.TestCase):
    def test_nfl_confirmation_remains_excluded(self):
        rows = {x["consumer"]: x for x in json.loads(Path("config/provider_consumer_registry_v1.json").read_text())["consumers"]}
        nfl = rows["NFL_2026_CONFIRMATION"]
        self.assertEqual(nfl["migration_state"], "EXCLUDED")
        self.assertEqual(nfl["preferred_provider"], "FROZEN_UNCHANGED")


if __name__ == "__main__":
    unittest.main()
