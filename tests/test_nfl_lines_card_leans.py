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


def _ticket(total: dict | None = None) -> dict:
    return {
        "slate": "2026-09-20",
        "games": [
            {
                "home": "BAL",
                "away": "KC",
                "markets": [
                    {"market": "spread", "line": 3.5, "away_or_over_price": -110, "home_or_under_price": -110, "raw": "Spread +3.5 -110 -110"},
                    # High total so the frozen model is guaranteed to like the under, on a
                    # calibration block with real history behind it.
                    total or {"market": "total", "line": 60.5, "away_or_over_price": -120, "home_or_under_price": 100, "raw": "Total 60.5 -120 +100"},
                    {"market": "team_total", "line": 10.5, "away_or_over_price": -110, "home_or_under_price": -110,
                     "raw": "TeamTotal Ravens 10.5 -110 -110", "team": "BAL", "player": None},
                    {"market": "pass_yards", "line": 245.5, "away_or_over_price": -110, "home_or_under_price": -110,
                     "raw": 'Prop "Lamar Jackson" PassYards 245.5 -110 -110', "team": None, "player": "Lamar Jackson"},
                ],
            }
        ],
    }


class NflCardLeanTests(unittest.TestCase):
    def _run(self, history: list[dict] | None = None, total: dict | None = None) -> tuple[dict, str]:
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "ticket.json").write_text(json.dumps(_ticket(total)), encoding="utf-8")
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

    def test_unstamped_manual_quotes_fail_closed_without_absolute_model_leans(self):
        engine, md = self._run()
        self.assertEqual(engine["bet_proven_markets"], [])
        self.assertTrue(engine["residual_pricing_enabled"])
        game = engine["games"][0]
        self.assertEqual(game["picks"], [])
        self.assertEqual(game["leans"], [])
        self.assertIsNone(game["residual_research"])
        self.assertIn("NO_MODEL:RESIDUAL_", game["residual_status"])
        total = [m for m in game["markets"] if m["market"] == "total"][0]
        self.assertIsNone(total["pick"])
        self.assertIsNone(total["lean"])
        self.assertIn("research", md.lower())
        self.assertNotIn("model EV", md)

    def test_plus_money_keeps_original_quoted_price_without_promotion(self):
        _, md = self._run()
        self.assertIn("u+100", md)
        self.assertNotIn("BET", md)

    def test_extreme_absolute_total_never_surfaces_fabricated_ev(self):
        engine, md = self._run(total={"market": "total", "line": 20.5,
                                      "away_or_over_price": 100,
                                      "home_or_under_price": -120,
                                      "raw": "Total 20.5 +100 -120"})
        game = engine["games"][0]
        total = [m for m in game["markets"] if m["market"] == "total"][0]
        self.assertIsNone(total["lean"])
        self.assertIsNone(total["pick"])
        self.assertNotIn("model EV", md)

    def test_legacy_directional_price_signal_never_survives_residual_conversion(self):
        from datetime import date
        from math import floor
        from sportsedge.nfl_attempt9_live_forecast import load_runtime, raw_forecasts, recency_features
        feat = recency_features(_history(),home="BAL",away="KC",asof=date(2026,9,20))
        pred = float(raw_forecasts(load_runtime(),feat["vector"])["total"])
        line = floor(pred - 0.5) + 0.5
        self.assertTrue(0 < pred - line <= 1.0)
        engine, md = self._run(total={"market":"total","line":line,
                         "away_or_over_price":-130,"home_or_under_price":110,
                         "raw":f"Total {line} -130 +110"})
        total=[m for m in engine["games"][0]["markets"] if m["market"]=="total"][0]
        self.assertIsNone(total["lean"])
        self.assertNotIn("model EV",md)

    def test_spread_requires_residual_paired_context(self):
        engine, md = self._run()
        spread = [m for m in engine["games"][0]["markets"] if m["market"]=="spread"][0]
        self.assertTrue(spread["no_model"].startswith("NO_MODEL"))
        self.assertIn("Spread KC +3.5 -110 / BAL -3.5 -110",md)
        self.assertNotIn("NO_MODEL:",md)

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


class NflHistoryTeamAliasTests(unittest.TestCase):
    def test_nflverse_la_rams_code_maps_to_intake_lar(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import run_nfl_lines_card as card
        finally:
            sys.path.pop(0)
        rows = card._history_rows({"games": [
            {"date": "2026-10-04", "home": "LA", "away": "SF", "hs": 20, "as": 17, "home_qb": "Matthew Stafford"},
            {"date": "2026-10-04", "home": "LAC", "away": "OAK", "hs": 24, "as": 10},
        ]})
        self.assertEqual(rows[0]["home"], "LAR")
        self.assertEqual(rows[0]["away"], "SF")
        self.assertEqual(rows[1]["home"], "LAC")
        self.assertEqual(rows[1]["away"], "LV")
        from datetime import date
        self.assertEqual(card._last_start_qb(rows, "LAR", date(2026, 10, 11))["qb"], "Matthew Stafford")


if __name__ == "__main__":
    unittest.main()
