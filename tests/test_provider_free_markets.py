from pathlib import Path
import unittest


class ProviderFreeMarketsTests(unittest.TestCase):
    def test_free_entrypoint_is_game_market_only(self):
        text = Path("sportsedge/free_game_market_acquisition.py").read_text()
        self.assertIn("Acquire ML/RL/totals from ESPN first", text)
        self.assertNotIn("fetch_mlb_player_prop_quotes", text)
        self.assertNotIn("NRFI", text)
        self.assertNotIn("YRFI", text)


if __name__ == "__main__":
    unittest.main()
