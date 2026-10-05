"""NFL manual-board emit matches the MLB card contract."""

from __future__ import annotations

import unittest

from scripts.run_auto_nfl_resilient import build_card


class NflAutoEmitTest(unittest.TestCase):
    def test_zero_quotes_is_the_only_infrastructure_block(self) -> None:
        card = build_card([])
        self.assertEqual(card["run_status"], "BLOCKED_NO_ODDS")
        self.assertEqual(card["funnel"]["odds_rows_fetched"], 0)
        self.assertFalse(card["odds_api_called"])
        self.assertFalse(card["governance"]["official_model_p"])
        self.assertFalse(card["governance"]["truth_gate"])

    def test_positive_edge_side_is_a_bet_without_invented_lines(self) -> None:
        card = build_card([
            {
                "game_id": "KC@BUF",
                "home_team": "BUF",
                "away_team": "KC",
                "quotes": [
                    {"market": "spread", "side": "AWAY", "line": 3.0, "american_odds": 150},
                    {"market": "spread", "side": "HOME", "line": -3.0, "american_odds": -130},
                ],
            }
        ])
        self.assertEqual(card["run_status"], "READY")
        self.assertEqual(card["market_input_source"], "MANUAL_SCREENSHOT_BOARD")
        self.assertEqual(card["forecast_source"], "ATTEMPT9_INTERCEPT_BASELINE")
        priced = [row for row in card["results"] if row.get("model_p") is not None]
        self.assertEqual(len(priced), 2)
        bets = [row for row in card["results"] if row.get("model_p") is not None and row.get("edge") is not None and float(row["edge"]) > 0]
        self.assertEqual(card["funnel"]["bets_emitted"], len(bets))
        self.assertGreaterEqual(len(bets), 1)
        self.assertTrue(all(row["bet_status"] == "BET" for row in bets))
        self.assertEqual(card["results"][0]["line"], 3.0)
        self.assertIsNotNone(card.get("full_board"))

    def test_no_edge_slate_is_success(self) -> None:
        card = build_card([
            {
                "game_id": "KC@BUF",
                "home_team": "BUF",
                "away_team": "KC",
                "quotes": [
                    {"market": "moneyline", "side": "HOME", "american_odds": -500},
                ],
            }
        ])
        self.assertEqual(card["run_status"], "READY")
        self.assertEqual(card["funnel"]["bets_emitted"], 0)
        self.assertEqual(card["results"][0]["reason"], "NO_EDGE")


if __name__ == "__main__":
    unittest.main()
