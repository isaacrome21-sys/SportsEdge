"""NFL phone card: totals have no out-of-sample edge, so they render as leans, never picks."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _history() -> list[dict]:
    games = []
    for i in range(8):
        day = f"2026-09-{i + 1:02d}"
        games.append({"date": day, "id": f"a{i}", "home": "KC", "away": "LV", "hs": 27, "as": 20})
        games.append({"date": day, "id": f"b{i}", "home": "BAL", "away": "CIN", "hs": 24, "as": 21})
    return games


def _ticket() -> dict:
    return {
        "slate": "2026-09-20",
        "games": [
            {
                "home": "BAL",
                "away": "KC",
                "markets": [
                    {"market": "spread", "line": 3.5, "away_or_over_price": -110, "home_or_under_price": -110, "raw": "Spread +3.5 -110 -110"},
                    # Absurdly low total so the frozen model is guaranteed to like the over.
                    {"market": "total", "line": 20.5, "away_or_over_price": 100, "home_or_under_price": -120, "raw": "Total 20.5 +100 -120"},
                    {"market": "team_total", "line": 10.5, "away_or_over_price": -110, "home_or_under_price": -110,
                     "raw": "TeamTotal Ravens 10.5 -110 -110", "team": "BAL", "player": None},
                    {"market": "pass_yards", "line": 245.5, "away_or_over_price": -110, "home_or_under_price": -110,
                     "raw": 'Prop "Lamar Jackson" PassYards 245.5 -110 -110', "team": None, "player": "Lamar Jackson"},
                ],
            }
        ],
    }


class NflCardLeanTests(unittest.TestCase):
    def _run(self) -> tuple[dict, str]:
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "ticket.json").write_text(json.dumps(_ticket()), encoding="utf-8")
            (t / "hist.json").write_text(json.dumps(_history()), encoding="utf-8")
            env = {"PYTHONPATH": str(ROOT)}
            subprocess.run(
                [sys.executable, "scripts/run_nfl_lines_card.py", "--input", str(t / "ticket.json"),
                 "--history", str(t / "hist.json"), "--output", str(t / "card.json")],
                cwd=ROOT, env=env, check=True,
            )
            subprocess.run(
                [sys.executable, "scripts/render_nfl_myspari_card.py", "--engine-output", str(t / "card.json"),
                 "--snapshot", str(t / "ticket.json"), "--pre-context", "--out-dir", str(t / "out")],
                cwd=ROOT, env=env, check=True,
            )
            return json.loads((t / "card.json").read_text()), (t / "out" / "card.md").read_text()

    def test_total_is_lean_not_pick(self):
        engine, md = self._run()
        self.assertEqual(engine["bet_proven_markets"], [])
        game = engine["games"][0]
        self.assertEqual(game["picks"], [])
        total = [m for m in game["markets"] if m["market"] == "total"][0]
        self.assertIsNone(total["pick"])
        self.assertIsNotNone(total["lean"])
        self.assertTrue(total["lean"]["lean_only"])
        self.assertEqual(total["lean"]["selection"], "Over")
        self.assertIn("LEAN (no proven edge, not a bet): Over 20.5", md)
        self.assertIn("All props, sides, and totals", md)
        self.assertIn("both_sides=True", md)
        self.assertIn("passing_yards", md)
        self.assertIn("Price needed", md)
        self.assertIn("NOT OFFICIAL", md)
        self.assertNotIn("OFFICIAL_BET", md)
        self.assertIn("No bets", md)
        self.assertNotIn("Score-B", md)

    def test_plus_money_shows_plus_sign(self):
        _, md = self._run()
        self.assertIn("Over 20.5 @ +100", md)

    def test_team_total_and_prop_are_track_only(self):
        engine, md = self._run()
        game = engine["games"][0]
        self.assertEqual(game["picks"], [])
        for m in game["markets"]:
            if m["market"] in {"team_total", "pass_yards"}:
                self.assertIsNone(m.get("pick"))
                self.assertTrue(m["no_model"].startswith("NO_MODEL"))
        self.assertIn("TeamTotal Ravens 10.5 -110 -110: TRACK ONLY (not a bet): team totals tested, no edge", md)
        self.assertIn("PassYards 245.5 -110 -110: TRACK ONLY (not a bet): no free historical prop closing lines", md)

    def test_spread_still_held(self):
        engine, md = self._run()
        spread = [m for m in engine["games"][0]["markets"] if m["market"] == "spread"][0]
        self.assertTrue(spread["no_model"].startswith("NO_MODEL"))


if __name__ == "__main__":
    unittest.main()
