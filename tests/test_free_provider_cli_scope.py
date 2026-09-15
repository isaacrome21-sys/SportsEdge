from pathlib import Path
import unittest


class FreeProviderCLIScopeTests(unittest.TestCase):
    def test_cli_is_context_only(self):
        text = Path("scripts/run_free_mlb_game_markets.py").read_text()
        self.assertIn('"authority": "MARKET_CONTEXT_ONLY"', text)
        self.assertIn('"model_p": None', text)
        self.assertIn('"promotion_authority": False', text)
        self.assertIn('"staking_authority": False', text)
        self.assertIn('"official_authority": False', text)
        self.assertIn("paid_fetch=None", text)


if __name__ == "__main__":
    unittest.main()
