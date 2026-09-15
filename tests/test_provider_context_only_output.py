from pathlib import Path
import unittest


class ProviderContextOnlyOutputTests(unittest.TestCase):
    def test_free_cli_cannot_emit_official_authority(self):
        text = Path("scripts/run_free_mlb_game_markets.py").read_text()
        self.assertIn('"authority": "MARKET_CONTEXT_ONLY"', text)
        self.assertIn('"official_authority": False', text)
        self.assertNotIn('"official_authority": True', text)
        self.assertNotIn('"promotion_authority": True', text)


if __name__ == "__main__":
    unittest.main()
