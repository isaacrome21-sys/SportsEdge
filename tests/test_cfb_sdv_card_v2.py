import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "cfb_sdv_card_v2",
    Path(__file__).resolve().parents[1] / "scripts" / "run_cfb_sdv_card_v2.py",
)
card = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(card)


class CfbSdvCardV2Test(unittest.TestCase):
    def test_floor_and_same_game_guard(self):
        rows = card.price_game("g", 45.0, 10.0, [
            {"market": "MONEYLINE", "side": "HOME", "american_odds": 200},
            {"market": "MONEYLINE", "side": "AWAY", "american_odds": -250},
            {"market": "SPREAD", "side": "HOME", "line": -3.5, "american_odds": -110},
            {"market": "SPREAD", "side": "AWAY", "line": 3.5, "american_odds": -110},
        ])
        bets = [r for r in rows if r["bet_status"] == "BET"]
        self.assertEqual(len(bets), 1)
        self.assertEqual(bets[0]["market"], "MONEYLINE")
        self.assertTrue(any(r["reason"] == "SAME_GAME_GUARD" for r in rows))
        self.assertEqual(rows[1]["bet_status"], "PASS")

    def test_paired_devig_sums_to_one(self):
        rows = card.price_game("g", 28.0, 24.0, [
            {"market": "SPREAD", "side": "HOME", "line": -3.5, "american_odds": -110},
            {"market": "SPREAD", "side": "AWAY", "line": 3.5, "american_odds": -110},
        ])
        self.assertAlmostEqual(rows[0]["market_p"] + rows[1]["market_p"], 1.0, places=3)
        self.assertEqual(rows[0]["devig"], "PAIRED_PROPORTIONAL")
        self.assertAlmostEqual(rows[0]["model_p"] + rows[1]["model_p"], 1.0, places=3)

    def test_total_symmetry(self):
        rows = card.price_game("g", 30.0, 22.5, [
            {"market": "TOTAL", "side": "OVER", "line": 52.5, "american_odds": -110},
            {"market": "TOTAL", "side": "UNDER", "line": 52.5, "american_odds": -110},
        ])
        self.assertAlmostEqual(rows[0]["model_p"], 0.5, places=3)


if __name__ == "__main__":
    unittest.main()
