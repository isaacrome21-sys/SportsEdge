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


def _starters(teams: dict | None = None, retrieved_at: str = "2026-09-20T15:00:00Z") -> dict:
    """Authoritative-starter fixture (same shape fetch_espn_starters returns)."""
    teams = teams if teams is not None else {"KC": "Patrick Mahomes", "BAL": "Lamar Jackson"}
    return {"source": "TEST_FIXTURE", "retrieved_at": retrieved_at,
            "teams": {t: (v if isinstance(v, dict) else
                          {"names": [v], "injury_report_checked": True, "injury_status": ""})
                      for t, v in teams.items()}}


_DEFAULT = object()


class NflCardLeanTests(unittest.TestCase):
    def _run(self, history: list[dict] | None = None, total: dict | None = None,
             drop_player: str | None = None, starters: object = _DEFAULT,
             props: list[dict] | None = None) -> tuple[dict, str]:
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            ticket = _ticket(total)
            if drop_player:
                for g in ticket["games"]:
                    g["markets"] = [m for m in g["markets"] if m.get("player") != drop_player]
            if props is not None:
                for g in ticket["games"]:
                    g["markets"] = [m for m in g["markets"] if not m.get("player")] + [
                        {"market": "pass_yards", "line": 250.5, "away_or_over_price": -110,
                         "home_or_under_price": -110, "raw": f'Prop "{p["player"]}" PassYards 250.5 -110 -110',
                         "quote_retrieved_at": ticket["observed_at"], **p} for p in props]
            (t / "ticket.json").write_text(json.dumps(ticket), encoding="utf-8")
            (t / "hist.json").write_text(json.dumps(_history() if history is None else history), encoding="utf-8")
            env = {"PYTHONPATH": str(ROOT)}
            extra = []
            if starters is _DEFAULT:
                starters = _starters()
            if starters is not None:
                (t / "starters.json").write_text(json.dumps(starters), encoding="utf-8")
                extra = ["--starters", str(t / "starters.json")]
            subprocess.run(
                [sys.executable, "scripts/run_nfl_lines_card.py", "--input", str(t / "ticket.json"),
                 "--history", str(t / "hist.json"), "--output", str(t / "card.json"), *extra],
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
        # Both confirmed starters match the model's QBs: no QB lines.
        self.assertNotIn("QB change", md)
        self.assertNotIn("QB not confirmed", md)

    # ---- #3017 legacy-route QB safeguard (review 5731129764) ----

    def _mains(self, engine):
        mains = [m for m in engine["games"][0]["markets"] if m.get("residual_mode")]
        self.assertTrue(mains)
        return mains

    def _assert_all_blocked(self, engine, code):
        for m in self._mains(engine):
            self.assertIsNone(m["lean"])
            self.assertEqual(m["lean_block"], code)
        self.assertEqual(engine["games"][0]["leans"], [])

    def test_confirmed_starters_match_model_no_block(self):
        engine, _ = self._run()
        self.assertIsNone(engine["games"][0]["context"]["qb_check"]["block"])
        for m in self._mains(engine):
            self.assertIsNone(m["lean_block"])

    def test_confirmed_starter_differs_from_model_qb_blocks_change(self):
        engine, md = self._run(starters=_starters({"KC": "Patrick Mahomes", "BAL": "Tyler Huntley"}))
        self.assertEqual(engine["games"][0]["context"]["qb_check"]["teams"]["BAL"]["verdict"], "QB_CHANGE")
        self._assert_all_blocked(engine, "NO_LEAN:QB_CHANGE_UNMODELED")
        self.assertIn("QB change (BAL): confirmed starter Tyler Huntley", md)
        self.assertIn("built on Lamar Jackson", md)

    def test_no_starter_source_fails_closed(self):
        engine, md = self._run(starters=None)
        self.assertEqual(engine["games"][0]["context"]["qb_check"]["teams"]["KC"]["verdict"],
                         "STARTER_SOURCE_UNAVAILABLE")
        self._assert_all_blocked(engine, "NO_LEAN:QB_STARTER_UNVERIFIED")
        self.assertIn("starting QB not confirmed", md)

    def test_props_alone_never_confirm_a_starter(self):
        # Both QBs have DK props (default ticket) but no authoritative source.
        engine, _ = self._run(starters=None)
        corr = engine["games"][0]["context"]["qb_check"]["prop_corroboration"]
        self.assertEqual(corr["teams"], {})
        self._assert_all_blocked(engine, "NO_LEAN:QB_STARTER_UNVERIFIED")

    def test_absent_confirmed_starter_for_one_team_blocks(self):
        engine, _ = self._run(starters=_starters({"BAL": "Lamar Jackson"}))
        self.assertEqual(engine["games"][0]["context"]["qb_check"]["teams"]["KC"]["verdict"],
                         "STARTER_TEAM_MISSING")
        self._assert_all_blocked(engine, "NO_LEAN:QB_STARTER_UNVERIFIED")

    def test_same_surname_qbs_on_opposite_teams_detects_change(self):
        # Old surname pooling: "Jackson" prop for KC's backup matched BAL's
        # Lamar Jackson and passed. Team-bound full names must catch it.
        engine, _ = self._run(
            starters=_starters({"KC": "Desmond Jackson", "BAL": "Lamar Jackson"}),
            props=[{"player": "Lamar Jackson", "team": "BAL"}, {"player": "Desmond Jackson", "team": "KC"}])
        teams = engine["games"][0]["context"]["qb_check"]["teams"]
        self.assertEqual((teams["KC"]["verdict"], teams["BAL"]["verdict"]), ("QB_CHANGE", "MATCH"))
        self._assert_all_blocked(engine, "NO_LEAN:QB_CHANGE_UNMODELED")

    def test_same_surname_model_qb_is_not_a_match(self):
        hist = _history()
        for g in hist:
            if g["home"] == "KC":
                g["home_qb"] = "Shane Jackson"
        engine, _ = self._run(hist, starters=_starters({"KC": "Patrick Mahomes", "BAL": "Lamar Jackson"}))
        self.assertEqual(engine["games"][0]["context"]["qb_check"]["teams"]["KC"]["verdict"], "QB_CHANGE")

    def test_prop_assigned_to_wrong_team_blocks(self):
        engine, md = self._run(props=[{"player": "Patrick Mahomes", "team": "BAL"},
                                      {"player": "Lamar Jackson", "team": "BAL"}])
        conflicts = engine["games"][0]["context"]["qb_check"]["prop_corroboration"]["conflicts"]
        self.assertEqual(conflicts, [{"player": "Patrick Mahomes", "code": "PROP_TEAM_CONFLICT"}])
        self._assert_all_blocked(engine, "NO_LEAN:QB_STARTER_UNVERIFIED")
        self.assertIn("QB prop conflict: Patrick Mahomes", md)

    def test_prop_for_a_qb_who_is_neither_starter_blocks(self):
        engine, _ = self._run(props=[{"player": "Patrick Mahomes", "team": None},
                                     {"player": "Lamar Jackson", "team": None},
                                     {"player": "Tyler Huntley", "team": None}])
        conflicts = engine["games"][0]["context"]["qb_check"]["prop_corroboration"]["conflicts"]
        self.assertEqual([c["code"] for c in conflicts], ["PROP_QB_NOT_A_CONFIRMED_STARTER"])
        self._assert_all_blocked(engine, "NO_LEAN:QB_STARTER_UNVERIFIED")

    def test_ambiguous_or_surname_only_starter_rejected(self):
        for kc in ({"names": ["Patrick Mahomes", "Carson Wentz"], "injury_report_checked": True},
                   {"names": ["Mahomes"], "injury_report_checked": True}):
            engine, _ = self._run(starters=_starters({"KC": kc, "BAL": "Lamar Jackson"}))
            self.assertEqual(engine["games"][0]["context"]["qb_check"]["teams"]["KC"]["verdict"],
                             "STARTER_NAME_AMBIGUOUS")
            self._assert_all_blocked(engine, "NO_LEAN:QB_STARTER_UNVERIFIED")

    def test_stale_or_untimestamped_starter_source_blocks(self):
        for doc, code in ((_starters(retrieved_at="2026-09-19T15:00:00Z"), "STARTER_STALE"),
                          (_starters(retrieved_at="2026-09-20T17:00:00Z"), "STARTER_STALE"),
                          ({**_starters(), "retrieved_at": None}, "STARTER_TIMESTAMP_MISSING")):
            engine, _ = self._run(starters=doc)
            self.assertEqual(engine["games"][0]["context"]["qb_check"]["teams"]["KC"]["verdict"], code)
            self._assert_all_blocked(engine, "NO_LEAN:QB_STARTER_UNVERIFIED")

    def test_starter_on_injury_report_or_unchecked_report_blocks(self):
        for kc, code in (({"names": ["Patrick Mahomes"], "injury_report_checked": True,
                           "injury_status": "Questionable"}, "STARTER_INJURY_LISTED"),
                         ({"names": ["Patrick Mahomes"]}, "STARTER_SOURCE_UNAVAILABLE")):
            engine, _ = self._run(starters=_starters({"KC": kc, "BAL": "Lamar Jackson"}))
            self.assertEqual(engine["games"][0]["context"]["qb_check"]["teams"]["KC"]["verdict"], code)
            self._assert_all_blocked(engine, "NO_LEAN:QB_STARTER_UNVERIFIED")

    def test_suffix_and_accent_normalized_full_name_matches(self):
        hist = _history()
        for g in hist:
            if g["home"] == "BAL":
                g["home_qb"] = "Lamar Jackson Jr."
        engine, _ = self._run(hist)
        self.assertEqual(engine["games"][0]["context"]["qb_check"]["teams"]["BAL"]["verdict"], "MATCH")

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


class NflEspnStarterFetchTests(unittest.TestCase):
    """fetch_espn_starters against canned ESPN payloads (no network)."""

    def _getter(self, *, kc_depth=None, injuries=None, fail=()):
        from sportsedge.nfl_qb_starter_check import ESPN_BASE
        board = {"events": [{"id": "e1", "competitions": [{"competitors": [
            {"homeAway": "away", "team": {"id": "12", "abbreviation": "KC"}},
            {"homeAway": "home", "team": {"id": "33", "abbreviation": "BAL"}}]}]}]}
        def depth(name, aid):
            return {"depthchart": [{"name": "Base", "positions": {"qb": {"athletes": [
                {"id": aid, "displayName": name}, {"id": "9", "displayName": "Backup Guy"}]}}}]}
        pages = {
            f"{ESPN_BASE}/summary?event=e1": {"injuries": injuries or []},
            f"{ESPN_BASE}/teams/12/depthcharts": kc_depth or depth("Patrick Mahomes", "3139477"),
            f"{ESPN_BASE}/teams/33/depthcharts": depth("Lamar Jackson", "3916387"),
        }
        def get(url):
            if any(f in url for f in fail):
                raise OSError("down")
            if "scoreboard" in url:
                return board
            return pages[url]
        return get

    def _fetch(self, **kw):
        from datetime import date, datetime, timezone
        from sportsedge.nfl_qb_starter_check import fetch_espn_starters
        return fetch_espn_starters([{"away": "KC", "home": "BAL"}], date(2026, 9, 20), getter=self._getter(**kw),
                                   now=datetime(2026, 9, 20, 15, tzinfo=timezone.utc))

    def test_depth_chart_qb1_with_clean_injury_report_confirms(self):
        from sportsedge.nfl_qb_starter_check import resolve_starter
        doc = self._fetch()
        r = resolve_starter(doc, "KC", "2026-09-20T16:00:00Z")
        self.assertEqual((r["status"], r["name"], r["athlete_id"]), ("CONFIRMED", "Patrick Mahomes", "3139477"))
        self.assertEqual(doc["retrieved_at"], "2026-09-20T15:00:00+00:00")

    def test_qb1_out_on_injury_report_is_not_confirmed(self):
        from sportsedge.nfl_qb_starter_check import resolve_starter
        doc = self._fetch(injuries=[{"team": {"id": "12"}, "injuries": [
            {"athlete": {"id": "3139477"}, "status": "Out"}]}])
        self.assertEqual(resolve_starter(doc, "KC", "2026-09-20T16:00:00Z")["status"], "STARTER_INJURY_LISTED")

    def test_conflicting_qb1_across_formations_is_ambiguous(self):
        from sportsedge.nfl_qb_starter_check import resolve_starter
        kc = {"depthchart": [
            {"positions": {"qb": {"athletes": [{"id": "1", "displayName": "Patrick Mahomes"}]}}},
            {"positions": {"qb": {"athletes": [{"id": "2", "displayName": "Carson Wentz"}]}}}]}
        doc = self._fetch(kc_depth=kc)
        self.assertEqual(resolve_starter(doc, "KC", "2026-09-20T16:00:00Z")["status"], "STARTER_NAME_AMBIGUOUS")

    def test_fetch_failures_fail_closed(self):
        from sportsedge.nfl_qb_starter_check import resolve_starter
        doc = self._fetch(fail=("teams/12/depthcharts",))
        self.assertEqual(resolve_starter(doc, "KC", "2026-09-20T16:00:00Z")["status"], "STARTER_TEAM_MISSING")
        doc = self._fetch(fail=("summary",))
        self.assertEqual(resolve_starter(doc, "BAL", "2026-09-20T16:00:00Z")["status"], "STARTER_SOURCE_UNAVAILABLE")
        doc = self._fetch(fail=("scoreboard",))
        self.assertEqual(resolve_starter(doc, "BAL", "2026-09-20T16:00:00Z")["status"], "STARTER_TEAM_MISSING")


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
