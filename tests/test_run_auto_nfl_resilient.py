import json
import unittest
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_auto_nfl_resilient import build_card


class RunAutoNflResilientTests(unittest.TestCase):
    def test_positive_edge_is_a_bet_and_board_sees_model_p(self):
        card = build_card([{
            "game_id": "g1",
            "home_team": "H",
            "away_team": "A",
            "margin": 3.0,
            "total": 44.0,
            "quotes": [{"market": "MONEYLINE", "side": "HOME", "american_odds": 150}],
        }])
        self.assertEqual(card["run_status"], "READY")
        self.assertEqual(card["funnel"]["odds_rows_fetched"], 1)
        self.assertIsNotNone(card["results"][0]["model_p"])
        self.assertGreater(card["results"][0]["edge"], 0)
        self.assertEqual(card["results"][0]["bet_status"], "BET")
        self.assertEqual(card["funnel"]["bets_emitted"], 1)
        self.assertFalse(card["odds_api_called"])
        priced = [row for row in card["board"]["rows"] if row.get("model_p") is not None]
        self.assertTrue(priced)

    def test_no_edge_slate_is_success(self):
        card = build_card([{
            "game_id": "g1",
            "margin": 0.0,
            "total": 44.0,
            "quotes": [{"market": "MONEYLINE", "side": "HOME", "american_odds": -200}],
        }])
        self.assertEqual(card["run_status"], "READY")
        self.assertEqual(card["funnel"]["bets_emitted"], 0)
        self.assertEqual(card["results"][0]["reason"], "NO_EDGE")

    def test_zero_quotes_is_the_only_infrastructure_block(self):
        card = build_card([{"game_id": "g1", "margin": 3.0, "total": 44.0}])
        self.assertEqual(card["run_status"], "BLOCKED_NO_ODDS")
        script = ROOT / "scripts" / "run_auto_nfl_resilient.py"
        proc = subprocess.run([sys.executable, str(script), "--board", "[]"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["run_status"], "BLOCKED_NO_ODDS")


if __name__ == "__main__":
    unittest.main()
