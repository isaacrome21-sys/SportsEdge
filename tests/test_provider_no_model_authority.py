from pathlib import Path
import unittest


class ProviderNoModelAuthorityTests(unittest.TestCase):
    def test_provider_modules_do_not_generate_model_probability(self):
        for path in ("sportsedge/market_provider_contract.py", "sportsedge/market_provider_router.py", "sportsedge/free_game_market_acquisition.py"):
            text = Path(path).read_text()
            self.assertNotIn("model_p =", text.lower(), path)
            self.assertNotIn("OFFICIAL_BET", text, path)


if __name__ == "__main__":
    unittest.main()
