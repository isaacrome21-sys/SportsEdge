import unittest
from scripts.run_nfl_card_v2 import price_game


class NFLCardTests(unittest.TestCase):
    def test_positive_edge_is_bet_and_same_game_guard(self):
        rows = price_game("g1", 30.0, 17.0, [
            {"market": "MONEYLINE", "side": "HOME", "american_odds": 150},
            {"market": "MONEYLINE", "side": "AWAY", "american_odds": -170},
            {"market": "SPREAD", "side": "HOME", "line": -3.5, "american_odds": -110},
            {"market": "SPREAD", "side": "AWAY", "line": 3.5, "american_odds": -110},
            {"market": "TOTAL", "side": "OVER", "line": 40.5, "american_odds": -110},
            {"market": "TOTAL", "side": "UNDER", "line": 40.5, "american_odds": -110},
        ])
        bets = [r for r in rows if r["bet_status"] == "BET"]
        self.assertLessEqual(sum(r["market"] in {"MONEYLINE", "SPREAD"} for r in bets), 1)
        self.assertLessEqual(sum(r["market"] == "TOTAL" for r in bets), 1)
        self.assertTrue(all(r["edge"] >= 0.02 for r in bets))

    def test_no_edge_passes(self):
        rows = price_game("g2", 24.0, 24.0, [
            {"market": "MONEYLINE", "side": "HOME", "american_odds": -110},
            {"market": "MONEYLINE", "side": "AWAY", "american_odds": -110},
        ])
        self.assertTrue(all(r["bet_status"] == "PASS" for r in rows))


if __name__ == "__main__":
    unittest.main()
