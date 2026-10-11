"""NFL fair-price check: DK vs Pinnacle / multi-book no-vig, never invented."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.sports.nfl import fair_odds as fo

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


def _book(key, h2h=None, spreads=None, totals=None):
    markets = []
    if h2h:
        markets.append({"key": "h2h", "outcomes": [{"name": n, "price": p} for n, p in h2h]})
    if spreads:
        markets.append({"key": "spreads", "outcomes": [{"name": n, "price": p, "point": pt} for n, p, pt in spreads]})
    if totals:
        markets.append({"key": "totals", "outcomes": [{"name": n, "price": p, "point": pt} for n, p, pt in totals]})
    return {"key": key, "markets": markets}


def _event(books, t="2026-10-11T17:00:00Z"):
    return {"id": "e1", "commence_time": t, "home_team": "Jacksonville Jaguars",
            "away_team": "Philadelphia Eagles", "bookmakers": books}


class FairOddsTests(unittest.TestCase):
    def test_devig_and_conversions(self):
        a, b = fo.devig_two_way(-110, -110)
        self.assertAlmostEqual(a, 0.5)
        self.assertAlmostEqual(b, 0.5)
        self.assertEqual(fo.prob_to_american(0.5), -100)
        self.assertEqual(fo.prob_to_american(0.25), 300)
        self.assertAlmostEqual(fo.american_to_decimal(+150), 2.5)

    def test_pinnacle_same_line_is_fair(self):
        e = _event([
            _book("draftkings", spreads=[("Jacksonville Jaguars", -105, -7.5), ("Philadelphia Eagles", -115, 7.5)]),
            _book("pinnacle", spreads=[("Jacksonville Jaguars", -125, -7.5), ("Philadelphia Eagles", 112, 7.5)]),
        ])
        rows = {r["side"]: r for r in fo.price_event(e)}
        jax = rows["Jacksonville Jaguars"]
        self.assertEqual(jax["source"], "Pinnacle no-vig")
        pa, _ = fo.devig_two_way(-125, 112)
        self.assertAlmostEqual(jax["fair_p"], pa)
        self.assertAlmostEqual(jax["ev"], pa * fo.american_to_decimal(-105) - 1)
        self.assertGreater(jax["ev"], 0.01)
        self.assertLess(rows["Philadelphia Eagles"]["ev"], 0)

    def test_different_line_is_not_used_and_one_soft_book_is_not_enough(self):
        e = _event([
            _book("draftkings", totals=[("Over", -112, 41.5), ("Under", -108, 41.5)]),
            _book("pinnacle", totals=[("Over", -105, 42.0), ("Under", -105, 42.0)]),
            _book("fanduel", totals=[("Over", -110, 41.5), ("Under", -110, 41.5)]),
        ])
        rows = fo.price_event(e)
        self.assertTrue(all(r["ev"] is None for r in rows))
        self.assertTrue(all(r["source"] == "no matching line elsewhere" for r in rows))

    def test_consensus_needs_three_books_at_same_line(self):
        soft = [("Over", -110, 41.5), ("Under", -110, 41.5)]
        e = _event([
            _book("draftkings", totals=[("Over", +100, 41.5), ("Under", -120, 41.5)]),
            _book("fanduel", totals=soft), _book("betmgm", totals=soft), _book("betrivers", totals=soft),
        ])
        over = [r for r in fo.price_event(e) if r["side"] == "Over"][0]
        self.assertEqual(over["source"], "3-book no-vig median")
        self.assertAlmostEqual(over["fair_p"], 0.5)
        self.assertAlmostEqual(over["ev"], 0.0)

    def test_render_flags_only_ev_above_threshold(self):
        e = _event([
            _book("draftkings", h2h=[("Jacksonville Jaguars", -350), ("Philadelphia Eagles", 310)],
                  spreads=[("Jacksonville Jaguars", -105, -7.5), ("Philadelphia Eagles", -115, 7.5)]),
            _book("pinnacle", h2h=[("Jacksonville Jaguars", -400), ("Philadelphia Eagles", 330)],
                  spreads=[("Jacksonville Jaguars", -116, -7.5), ("Philadelphia Eagles", 104, 7.5)]),
        ])
        md = fo.render_card(fo.upcoming([e], NOW), fetched_at=NOW)
        self.assertIn("PHI @ JAX", md)
        self.assertIn("✅ JAX -7.5 @ -105", md)
        self.assertIn("Pinnacle no-vig", md)
        self.assertIn("not a proven bet", md)
        for banned in ("OFFICIAL", "Truth Gate", "Model_P"):
            self.assertNotIn(banned, md)

    def test_far_off_price_is_flagged_verify_and_logged_for_clv(self):
        e = _event([
            _book("draftkings", spreads=[("Jacksonville Jaguars", +120, -7.5), ("Philadelphia Eagles", -150, 7.5)]),
            _book("pinnacle", spreads=[("Jacksonville Jaguars", -110, -7.5), ("Philadelphia Eagles", -110, 7.5)]),
        ])
        md = fo.render_card(fo.upcoming([e], NOW), fetched_at=NOW)
        self.assertIn("⚠️ JAX -7.5 @ +120", md)
        self.assertIn("verify", md)
        log = json.loads(md.split("<!-- sportsedge-clv-log ")[1].split(" -->")[0])
        self.assertEqual(len(log), 1)
        self.assertTrue(log[0]["stale"])
        self.assertEqual(log[0]["point"], -7.5)

    def test_started_games_are_dropped(self):
        e = _event([_book("draftkings", h2h=[("Jacksonville Jaguars", -350), ("Philadelphia Eagles", 310)])],
                   t="2026-10-11T11:00:00Z")
        self.assertEqual(fo.upcoming([e], NOW), [])

    def test_script_offline_render(self):
        e = _event([
            _book("draftkings", spreads=[("Jacksonville Jaguars", -105, -7.5), ("Philadelphia Eagles", -115, 7.5)]),
            _book("pinnacle", spreads=[("Jacksonville Jaguars", -125, -7.5), ("Philadelphia Eagles", 112, 7.5)]),
        ], t="2099-01-01T17:00:00Z")
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw.json"
            raw.write_text(json.dumps([e]), encoding="utf-8")
            out = Path(tmp) / "card.md"
            subprocess.run([sys.executable, "scripts/run_nfl_fair_odds_card.py", "--from-json", str(raw), "--out", str(out)],
                           cwd=ROOT, env={"PYTHONPATH": str(ROOT)}, check=True, capture_output=True)
            self.assertIn("NFL fair-price check", out.read_text(encoding="utf-8"))

    def test_request_cost_fits_budget_cap(self):
        sys.path.insert(0, str(ROOT))
        from scripts import run_nfl_fair_odds_card as card
        self.assertLessEqual(len(fo.BOOKMAKERS), 10)
        self.assertEqual(card.REQUEST_COST, 3)
        self.assertEqual(card.required_remaining(ROOT / "config/nfl_2026_provider_budget_v1.json"), 76 + 3)
        self.assertNotIn("apiKey", card.build_url())


if __name__ == "__main__":
    unittest.main()
