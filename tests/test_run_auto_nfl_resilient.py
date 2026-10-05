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

    def test_intercept_fallback_is_track_only_without_invented_edge(self) -> None:
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
        self.assertEqual(card["funnel"]["bets_emitted"], 0)
        self.assertTrue(all(row["bet_status"] == "TRACK" for row in priced))
        self.assertTrue(all(row["edge"] is None for row in priced))
        self.assertTrue(all(row["research_edge"] is not None for row in priced))
        self.assertTrue(all(row["reason"] == "INTERCEPT_BASELINE_ONLY" for row in priced))
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
        self.assertEqual(card["results"][0]["reason"], "INTERCEPT_BASELINE_ONLY")
        self.assertEqual(card["results"][0]["bet_status"], "TRACK")
        self.assertIsNone(card["results"][0]["edge"])


if __name__ == "__main__":
    unittest.main()
