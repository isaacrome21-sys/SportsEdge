import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FootballFullBoardCardWireTest(unittest.TestCase):
    def test_card_rows_with_model_p_render_without_inventing_lines(self):
        from scripts.run_football_full_board import board_from_card

        card = {
            "odds_api_called": False,
            "market_input_source": "MANUAL_SCREENSHOT_BOARD",
            "results": [
                {
                    "game_id": "g1",
                    "market": "moneyline",
                    "side": "HOME",
                    "american_odds": -110,
                    "model_p": 0.57,
                    "edge": 0.04,
                    "reason": "EDGE_POSITIVE",
                }
            ],
        }
        board = board_from_card("NFL", card)
        priced = [row for row in board["rows"] if row.get("model_p") is not None and row.get("market") == "moneyline"]
        self.assertTrue(priced)
        self.assertEqual(priced[0]["american_odds"], -110)
        self.assertIsNone(board["rows"][0].get("official_eligible") or False)

    def test_script_accepts_card_and_rejects_odds_api_cards(self):
        from scripts.run_football_full_board import board_from_card

        with self.assertRaises(SystemExit):
            board_from_card("NFL", {"odds_api_called": True, "results": []})
        out = ROOT / "artifacts" / "nfl_board_wire_test.json"
        card = ROOT / "artifacts" / "nfl_card_wire_test.json"
        card.parent.mkdir(parents=True, exist_ok=True)
        card.write_text(json.dumps({"odds_api_called": False, "results": []}), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "scripts/run_football_full_board.py", "--sport", "NFL", "--card", str(card), "--output", str(out)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
