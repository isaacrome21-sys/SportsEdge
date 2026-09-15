import json
from pathlib import Path
import unittest


class ProviderConsumerRegistryTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(Path("config/provider_consumer_registry_v1.json").read_text())
        self.rows = {x["consumer"]: x for x in self.payload["consumers"]}

    def test_game_context_is_free_first(self):
        row = self.rows["MLB_RUN_IT_GAME_MARKET_CONTEXT"]
        self.assertEqual(row["preferred_provider"], "ESPN_SCOREBOARD")
        self.assertEqual(set(row["markets"]), {"MONEYLINE", "RUN_LINE", "TOTALS"})
        self.assertEqual(row["migration_state"], "FREE_FIRST_ENTRYPOINT_ADDED")

    def test_extended_markets_do_not_claim_espn(self):
        row = self.rows["MLB_RUN_IT_EXTENDED_MARKETS"]
        self.assertEqual(row["preferred_provider"], "THE_ODDS_API")
        self.assertEqual(row["migration_state"], "NO_ELIGIBLE_ESPN_SUBSTITUTION")

    def test_frozen_nfl_confirmation_is_excluded(self):
        row = self.rows["NFL_2026_CONFIRMATION"]
        self.assertEqual(row["migration_state"], "EXCLUDED")
        self.assertEqual(row["preferred_provider"], "FROZEN_UNCHANGED")


if __name__ == "__main__":
    unittest.main()
