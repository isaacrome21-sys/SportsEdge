import json
import unittest

from scripts.run_auto_nhl_resilient import build_card


class NhlAutoCardTests(unittest.TestCase):
    def test_positive_edge_is_a_bet_and_no_edge_is_success(self):
        card = build_card(
            [{
                "game_id": "g1",
                "home": "Home",
                "away": "Away",
                "home_regulation_goals": 3.4,
                "away_regulation_goals": 2.2,
                "markets": [
                    {"market": "MONEYLINE", "away_or_over_price": 140, "home_or_under_price": -160},
                ],
            }],
            simulations=300,
        )
        self.assertEqual(card["run_status"], "READY")
        self.assertGreater(card["funnel"]["odds_rows_fetched"], 0)
        self.assertEqual(card["funnel"]["bets_emitted"], len(card["bets"]))
        self.assertTrue(all(row["model_p"] is not None for row in card["results"]))
        self.assertTrue(all(row["bet_status"] != "OFFICIAL_BET" for row in card["results"]))
        self.assertFalse(card["governance"]["odds_api_called"])
        priced = [row for row in card["results"] if row["edge"] is not None and row["edge"] <= 0]
        self.assertTrue(priced)
        self.assertTrue(all(row["bet_status"] == "NO_BET" for row in priced))

    def test_zero_quotes_is_the_only_infrastructure_block(self):
        card = build_card([{"game_id": "g1", "home_regulation_goals": 3.0, "away_regulation_goals": 2.5}])
        self.assertEqual(card["run_status"], "BLOCKED_NO_ODDS")
        self.assertEqual(card["funnel"]["odds_rows_fetched"], 0)
        self.assertEqual(card["funnel"]["bets_emitted"], 0)

    def test_quotes_without_rates_do_not_invent_lines(self):
        card = build_card([{
            "game_id": "g2",
            "american_odds": -110,
            "market": "MONEYLINE",
            "side": "HOME",
        }])
        self.assertEqual(card["run_status"], "READY")
        self.assertIsNone(card["results"][0]["model_p"])
        self.assertEqual(card["results"][0]["bet_status"], "NO_BET")
        self.assertEqual(json.loads(json.dumps(card))["governance"]["lines_invented"], False)


if __name__ == "__main__":
    unittest.main()
