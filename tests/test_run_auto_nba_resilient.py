import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_auto_nba_resilient.py"


def _run(board, output):
    env = {"PYTHONPATH": str(ROOT)}
    return subprocess.run(
        [sys.executable, str(RUNNER), "--output", str(output), "--board-json", json.dumps(board)],
        cwd=ROOT,
        env={**dict(**{k: v for k, v in __import__("os").environ.items()}), **env},
        text=True,
        capture_output=True,
        check=False,
    )


class NbaCardEmitTest(unittest.TestCase):
    def test_positive_edge_is_a_bet_and_no_edge_is_success(self):
        board = [{
            "away": "Celtics",
            "home": "Knicks",
            "margin": 8.0,
            "total": 220.0,
            "quotes": [
                {"market": "SPREAD", "side": "HOME", "line": -1.5, "american_odds": -110},
                {"market": "SPREAD", "side": "AWAY", "line": 1.5, "american_odds": -110},
                {"market": "TOTAL", "side": "OVER", "line": 230.5, "american_odds": -110},
                {"market": "TOTAL", "side": "UNDER", "line": 230.5, "american_odds": -110},
            ],
        }]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "card.json"
            proc = _run(board, out)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            card = json.loads(out.read_text())
            self.assertFalse(card["odds_api_called"])
            self.assertFalse(card["truth_gate"])
            self.assertFalse(card["official_model_p"])
            self.assertIsNone(card["governance"]["artifact_sha256"])
            self.assertNotEqual(card["governance"]["freeze_status"], "FROZEN")
            bets = [row for row in card["results"] if row["model_p"] is not None and row["edge"] is not None and row["edge"] > 0]
            self.assertGreater(len(bets), 0)
            self.assertEqual(card["funnel"]["bets_emitted"], len(bets))
            self.assertTrue(all(row["bet_status"] == "BET" for row in bets))
            self.assertTrue(any(row["bet_status"] == "NO_BET" for row in card["results"]))

    def test_zero_quotes_is_the_only_infrastructure_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "card.json"
            proc = _run([], out)
            self.assertEqual(proc.returncode, 2, proc.stderr)
            card = json.loads(out.read_text())
            self.assertEqual(card["run_status"], "BLOCKED_NO_ODDS")
            self.assertEqual(card["funnel"]["odds_rows_fetched"], 0)
            self.assertEqual(card["funnel"]["bets_emitted"], 0)


if __name__ == "__main__":
    unittest.main()
