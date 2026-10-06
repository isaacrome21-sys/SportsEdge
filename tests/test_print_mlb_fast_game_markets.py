import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import print_mlb_fast_game_markets as fast


class FastMlbGameBetOutputTests(unittest.TestCase):
    def test_only_actionable_game_markets_are_emitted_and_ranked(self):
        payload = {
            "rows": [
                {"market": "MONEYLINE", "side": "HOME", "american_odds": -120,
                 "model_p": .58, "edge": .04, "ev_per_dollar": .06,
                 "confidence_score": 88, "scored_status": "ACTIONABLE"},
                {"market": "PITCHER_K", "side": "OVER", "line": 6.5, "american_odds": -110,
                 "confidence_score": 95, "scored_status": "ACTIONABLE"},
                {"market": "TOTALS", "side": "UNDER", "line": 7.5, "american_odds": -105,
                 "model_p": .56, "edge": .03, "ev_per_dollar": .04,
                 "confidence_score": 82, "scored_status": "ACTIONABLE"},
                {"market": "F5_MONEYLINE", "side": "AWAY", "american_odds": +105,
                 "confidence_score": 91, "scored_status": "PASS"},
            ]
        }
        rows = fast.actionable_game_rows(payload)
        self.assertEqual([row["market"] for row in rows], ["MONEYLINE", "TOTALS"])

    def test_price_ceiling_or_other_pass_never_reappears_as_fast_bet(self):
        payload = {
            "rows": [
                {"market": "TEAM_TOTALS", "side": "OVER", "line": 3.5,
                 "american_odds": -170, "confidence_score": 90,
                 "scored_status": "PASS",
                 "presentation_reason_codes": ["PRICE_BEYOND_MAX_FAVORITE_-165"]},
            ]
        }
        self.assertEqual(fast.actionable_game_rows(payload), [])

    def test_cli_prints_machine_delimited_block(self):
        payload = {
            "rows": [
                {"market": "NRFI", "side": "YES", "american_odds": -115,
                 "model_p": .55, "edge": .02, "ev_per_dollar": .03,
                 "confidence_score": 84, "scored_status": "ACTIONABLE"},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "card.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with patch("sys.argv", ["print_mlb_fast_game_markets.py", "--card-json", str(path)]), \
                 patch("builtins.print") as printer:
                self.assertEqual(fast.main(), 0)
            printed = [call.args[0] for call in printer.call_args_list]
            self.assertEqual(printed[0], "FAST_MLB_GAME_BETS_BEGIN")
            self.assertEqual(printed[-1], "FAST_MLB_GAME_BETS_END")
            self.assertTrue(any('"pick":' in line for line in printed[1:-1]))


if __name__ == "__main__":
    unittest.main()
