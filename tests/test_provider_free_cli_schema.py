from pathlib import Path
import unittest


class ProviderFreeCLISchemaTests(unittest.TestCase):
    def test_output_schema_is_named(self):
        text = Path("scripts/run_free_mlb_game_markets.py").read_text()
        self.assertIn('"schema": "SPORTSEDGE_FREE_GAME_MARKETS_V1"', text)
        self.assertIn('"quotes": list(routed.quotes)', text)
        self.assertIn('"rejected": list(routed.rejected)', text)


if __name__ == "__main__":
    unittest.main()
