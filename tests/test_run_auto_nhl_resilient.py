import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NHLCardEmitTest(unittest.TestCase):
    def test_positive_edge_is_a_bet_and_zero_quotes_blocks(self):
        board = [
            {"game_id": "NYR@BOS", "away": "NYR", "home": "BOS", "market": "MONEYLINE", "side": "HOME", "american_odds": 200},
            {"game_id": "NYR@BOS", "away": "NYR", "home": "BOS", "market": "MONEYLINE", "side": "AWAY", "american_odds": -200},
            {"game_id": "NYR@BOS", "away": "NYR", "home": "BOS", "market": "TOTAL", "side": "OVER", "line": 6.5, "american_odds": -110},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "live_nhl_card.json"
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts/run_auto_nhl_resilient.py"), "--output", str(out), "--board-json", json.dumps(board)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            card = json.loads(out.read_text())
            self.assertFalse(card["odds_api_called"])
            self.assertFalse(card["official_model_p"])
            self.assertGreater(card["funnel"]["bets_emitted"], 0)
            self.assertTrue(any(row["model_p"] is not None and row["edge"] > 0 and row["bet_status"] == "BET" for row in card["results"]))
            empty = subprocess.run(
                [sys.executable, str(ROOT / "scripts/run_auto_nhl_resilient.py"), "--output", str(out), "--board-json", "[]"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(empty.returncode, 2)
            blocked = json.loads(out.read_text())
            self.assertEqual(blocked["run_status"], "BLOCKED_NO_ODDS")


if __name__ == "__main__":
    unittest.main()
