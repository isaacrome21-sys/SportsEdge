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
    ticket = {
        "slate": "2026-09-20",
        "observed_at": "2026-09-20T16:00:00Z",
        "games": [
            {
                "home": "BAL",
                "away": "KC",
                "commence_time": "2026-09-20T18:00:00Z",
                "markets": [
                    {"market": "spread", "line": 3.5, "away_or_over_price": -110, "home_or_under_price": -110, "raw": "Spread +3.5 -110 -110"},
                    # High total so the frozen model is guaranteed to like the under, on a
                    # calibration block with real history behind it.
                    total or {"market": "total", "line": 60.5, "away_or_over_price": -120, "home_or_under_price": 100, "raw": "Total 60.5 -120 +100"},
                    {"market": "team_total", "line": 10.5, "away_or_over_price": -110, "home_or_under_price": -110,
                     "raw": "TeamTotal Ravens 10.5 -110 -110", "team": "BAL", "player": None},
                    {"market": "pass_yards", "line": 245.5, "away_or_over_price": -110, "home_or_under_price": -110,
                     "raw": 'Prop "Lamar Jackson" PassYards 245.5 -110 -110', "team": None, "player": "Lamar Jackson"},
                    {"market": "pass_yards", "line": 265.5, "away_or_over_price": -110, "home_or_under_price": -110,
                     "raw": 'Prop "Patrick Mahomes" PassYards 265.5 -110 -110', "team": None, "player": "Patrick Mahomes"},
                ],
            }
        ],
    }
    for g in ticket["games"]:
        for market in g["markets"]:
            market["quote_retrieved_at"] = ticket["observed_at"]
    return ticket


class NflCardLeanTests(unittest.TestCase):
    def _run(self, history: list[dict] | None = None, total: dict | None = None,
             drop_player: str | None = None) -> tuple[dict, str]:
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            ticket = _ticket(total)
            if drop_player:
                for g in ticket["games"]:
                    g["markets"] = [m for m in g["markets"] if m.get("player") != drop_player]
            (t / "ticket.json").write_text(json.dumps(ticket), encoding="utf-8")
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

    def test_total_is_research_only_not_pick(self):
        engine, md = self._run()
        self.assertEqual(engine["bet_proven_markets"], [])
        self.assertEqual(engine["validated_markets"], [])
        game = engine["games"][0]
        self.assertEqual(game["picks"], [])
        self.assertIsNone(game["residual_research_error"])
        self.assertEqual({r["market"] for r in game["residual_research_prices"]},
                         {"moneyline", "spread", "total"} - {"moneyline"})
        self.assertTrue(all(r["eligible_as_bet"] is False for r in game["residual_research_prices"]))
        self.assertIn("Residual adjustments", md)

    def test_plus_money_quote_still_prints_with_plus_sign(self):
        _, md = self._run()
        self.assertIn("Under 60.5 @ +100", md)

    def test_absolute_total_outlier_shrinks_instead_of_large_model_ev(self):
        engine, _ = self._run(total={"market": "total", "line": 20.5, "away_or_over_price": 100,
                                     "home_or_under_price": -120, "raw": "Total 20.5 +100 -120"})
        game = engine["games"][0]
        total = [m for m in game["markets"] if m["market"] == "total"][0]
        self.assertIsNone(total["pick"])
        self.assertIsNone(game["residual_research_error"])
        expected = 20.5 + 0.15 * (game["context"]["projection"]["total"] - 20.5)
        self.assertAlmostEqual(total["residual_research_prices"][0]["fair_total"], expected, delta=0.015)
        self.assertTrue(all(0 <= p["estimate_p"] < 1 for p in total["residual_research_prices"]))

    def test_near_market_total_does_not_promote_price_only_under(self):
        from datetime import date
        from math import floor
        from sportsedge.nfl_attempt9_live_forecast import load_runtime, raw_forecasts, recency_features
        feat = recency_features(_history(), home="BAL", away="KC", asof=date(2026, 9, 20))
        pred = float(raw_forecasts(load_runtime(), feat["vector"])["total"])
        line = floor(pred - 0.5) + 0.5
        engine, _ = self._run(total={"market": "total", "line": line, "away_or_over_price": -130,
                                     "home_or_under_price": 110, "raw": f"Total {line} -130 +110"})
        game = engine["games"][0]
        total = [m for m in game["markets"] if m["market"] == "total"][0]
        self.assertIsNone(total["pick"])
        self.assertTrue(all(x["status"] == "RESEARCH_ONLY" for x in total["residual_research_prices"]))
        self.assertLess(abs(total["residual_research_adjustment"]), 0.5)
        self.assertIsNone(total["lean"])

    def test_spread_only_research_no_promotion(self):
        engine, md = self._run()
        spread = [m for m in engine["games"][0]["markets"] if m["market"] == "spread"][0]
        self.assertIsNone(spread["pick"])
        self.assertEqual(len(spread["residual_research_prices"]), 2)
        self.assertIn("Residual adjustments", md)
        self.assertNotIn("**BET**", md)

    def test_card_does_not_grant_any_official_authority(self):
        engine, md = self._run()
        self.assertEqual(engine["bet_proven_markets"], [])
        self.assertEqual(engine["validated_markets"], [])
        self.assertTrue(all(not p.get("eligible_as_bet", True)
                            for game in engine["games"]
                            for p in game["residual_research_prices"]))
        self.assertNotIn("**BET**", md)
        self.assertIn("NOT proven", md)

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

    def test_qb_change_blocks_side_total_ml_leans(self):
        hist = _history()
        for g in hist:
            if g["home"] == "BAL":
                g["home_qb"] = "Tyler Huntley"
        engine, md = self._run(hist)
        game = engine["games"][0]
        assert game["context"]["qb_change_flag"]
        mains = [m for m in game["markets"] if m.get("residual_mode")]
        self.assertTrue(mains)
        for m in mains:
            self.assertIsNone(m["lean"])
            self.assertEqual(m["lean_block"], "NO_LEAN:QB_CHANGE_UNMODELED")
        self.assertEqual(game["leans"], [])
        self.assertIn("QB change: the model was built on a different starter", md)

    def test_no_qb_change_no_block(self):
        engine, _ = self._run()
        for m in engine["games"][0]["markets"]:
            if m.get("residual_mode"):
                self.assertIsNone(m.get("lean_block"))

    def test_qb_unverified_blocks_when_a_starter_has_no_prop(self):
        hist = _history()
        for g in hist:
            if g["home"] == "KC":
                g["home_qb"] = "Patrick Mahomes"
        engine, md = self._run(hist, drop_player="Patrick Mahomes")
        game = engine["games"][0]
        self.assertFalse(game["context"].get("qb_change_flag"))
        self.assertEqual(game["context"]["qb_verified"]["KC"], False)
        for m in game["markets"]:
            if m.get("residual_mode"):
                self.assertIsNone(m["lean"])
                self.assertEqual(m["lean_block"], "NO_LEAN:QB_STARTER_UNVERIFIED")
        self.assertIn("starting QBs not confirmed", md)

    def test_qb_unverified_blocks_without_history(self):
        engine, _ = self._run([])
        for m in engine["games"][0]["markets"]:
            if m.get("residual_mode"):
                self.assertIsNone(m["lean"])

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
