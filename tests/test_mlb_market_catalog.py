import json
import unittest
from pathlib import Path


class MLBMarketCatalogTests(unittest.TestCase):
    def test_catalog_includes_full_supported_pregame_surface(self):
        payload = json.loads(Path("config/mlb_market_catalog.json").read_text())
        markets = set(payload["game_markets"] + payload["batter_markets"] + payload["pitcher_markets"] + payload["separate_protocol_markets"])
        required = {
            "MONEYLINE", "RUN_LINE", "TOTALS", "NRFI", "YRFI",
            "HOME_RUNS", "HITS", "TOTAL_BASES", "RBI", "RUNS",
            "HITS_RUNS_RBIS", "SINGLES", "DOUBLES", "TRIPLES",
            "BATTER_BB", "BATTER_K", "STOLEN_BASES",
            "PITCHER_K", "PITCHER_HITS_ALLOWED", "PITCHER_BB",
            "PITCHER_ER", "PITCHER_OUTS",
        }
        self.assertTrue(required.issubset(markets))

    def test_period_and_binary_markets_are_explicitly_separate(self):
        payload = json.loads(Path("config/mlb_market_catalog.json").read_text())
        self.assertIn("PITCHER_RECORD_WIN", payload["binary_markets_not_coerced"])
        self.assertIn("FIRST_HOME_RUN", payload["binary_markets_not_coerced"])
        self.assertIn("F5_MONEYLINE", payload["period_markets_not_coerced"])


if __name__ == "__main__":
    unittest.main()
