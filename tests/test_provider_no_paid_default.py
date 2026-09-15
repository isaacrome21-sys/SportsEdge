from pathlib import Path
import unittest


class ProviderNoPaidDefaultTests(unittest.TestCase):
    def test_free_context_cli_has_no_odds_api_key_dependency(self):
        text = Path("scripts/run_free_mlb_game_markets.py").read_text()
        self.assertNotIn("ODDS_API_KEY", text)
        self.assertNotIn("SPORTSEDGE_ODDS_API_KEY", text)
        self.assertIn("paid_fetch=None", text)


if __name__ == "__main__":
    unittest.main()
