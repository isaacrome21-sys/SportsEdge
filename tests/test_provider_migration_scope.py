import json
from pathlib import Path
import unittest


class ProviderMigrationScopeTests(unittest.TestCase):
    def test_only_game_context_is_marked_free_first(self):
        payload = json.loads(Path("config/provider_consumer_registry_v1.json").read_text())
        free_first = [x for x in payload["consumers"] if x["migration_state"] == "FREE_FIRST_ENTRYPOINT_ADDED"]
        self.assertEqual([x["consumer"] for x in free_first], ["MLB_RUN_IT_GAME_MARKET_CONTEXT"])


if __name__ == "__main__":
    unittest.main()
