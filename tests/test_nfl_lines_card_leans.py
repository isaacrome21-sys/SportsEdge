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
        games.append({"date": day, "id": f"a{i}", "home": "KC", "away": "LV", "hs": 27, "as": 20,
                      "home_qb": "Patrick Mahomes", "away_qb": "Geno Smith"})
        games.append({"date": day, "id": f"b{i}", "home": "BAL", "away": "CIN", "hs": 24, "as": 21,
                      "home_qb": "Lamar Jackson", "away_qb": "Joe Burrow"})
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
    def _run(self, history: list[dict] | None = None) -> tuple[dict, str]:
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "ticket.json").write_text(json.dumps(_ticket()), encoding="utf-8")
            (t / "hist.json").write_text(json.dumps(_history() if history is None else history), encoding="utf-8")
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
        self.assertIn("Team totals (1): TRACK ONLY (not a bet): team totals tested, no edge", md)
        self.assertIn("TeamTotal Ravens 10.5 -110 -110", md)
        self.assertIn("Props (1): TRACK ONLY (not a bet)", md)
        self.assertIn("no free historical prop closing lines", md)
        self.assertIn('Prop "Lamar Jackson" PassYards 245.5 -110 -110', md)

    def test_spread_still_held(self):
        engine, md = self._run()
        spread = [m for m in engine["games"][0]["markets"] if m["market"] == "spread"][0]
        self.assertTrue(spread["no_model"].startswith("NO_MODEL"))
        self.assertIn("Spread KC +3.5 -110 / BAL -3.5 -110: no pick: spreads held", md)
        self.assertNotIn("NO_MODEL:", md)

    def test_card_has_no_official_or_truth_gate_wording(self):
        _, md = self._run()
        for banned in ("OFFICIAL", "Truth Gate", "Model_P", "PRE-CONTEXT", "NOT FINAL"):
            self.assertNotIn(banned, md)

    def test_home_spread_side_is_mirrored_in_both_sides_table(self):
        engine, md = self._run()
        spread = {r["selection"]: r for r in engine["full_board"]["rows"]
                  if r["market"] == "spread" and r.get("game_id")}
        self.assertEqual(spread["AWAY"]["line"], 3.5)
        self.assertEqual(spread["HOME"]["line"], -3.5)
        self.assertNotIn("Price needed", md)

    def test_why_section_uses_only_retrieved_facts(self):
        engine, md = self._run()
        ctx = engine["games"][0]["context"]
        self.assertEqual(ctx["last_start_qb"]["BAL"]["qb"], "Lamar Jackson")
        self.assertIn("Why (from nflverse games):", md)
        self.assertIn("Model (Attempt 9): total", md)
        self.assertIn("Last listed starting QB (nflverse): KC Patrick Mahomes", md)
        self.assertIn("Injuries/inactives: not checked", md)
        # Lamar has a passing prop and is BAL's last starter: no QB-change flag.
        self.assertNotIn("QB check", md)

    def test_qb_change_flag_when_prop_qb_is_not_last_starter(self):
        hist = _history()
        for g in hist:
            if g["home"] == "BAL":
                g["home_qb"] = "Tyler Huntley"
        engine, md = self._run(hist)
        self.assertEqual(engine["games"][0]["context"]["qb_change_flag"], ["Lamar Jackson"])
        self.assertIn("QB check: DK has passing props for Lamar Jackson", md)

    def test_no_why_section_without_history_facts(self):
        _, md = self._run([])
        self.assertNotIn("Why (", md)
        self.assertNotIn("Injuries", md)
        self.assertNotIn("starting QB", md)


if __name__ == "__main__":
    unittest.main()
