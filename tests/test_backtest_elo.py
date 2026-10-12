"""Tests for sportsedge.backtest.elo. No network, no market data.

Hand-computed values below follow the module docstring formulas exactly
(NFL: K=20, HFA=65, 538-style MOV multiplier). They were derived with an
independent calculation, not by running the implementation.
"""
import unittest
import math
from datetime import datetime, timedelta

from sportsedge.backtest import elo
from sportsedge.backtest import report as backtest_report
from sportsedge.backtest import runner, splits


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


class TestEloMath(unittest.TestCase):
    def test_expected_home_hand_computed(self):
        t = elo.EloRatings("nfl")
        # 1 / (1 + 10^(-65/400)) = 0.592466
        self.assertTrue(approx(t.expected_home("A", "B"), 0.592466))
        self.assertTrue(approx(t.expected_home("B", "A"), 0.592466))
        # neutral site: no HFA
        self.assertTrue(approx(t.expected_home("A", "B", neutral=True), 0.5))

    def test_update_hand_computed(self):
        t = elo.EloRatings("nfl")
        diag = t.update_game("A", "B", 24, 20)
        # p_home=0.592466, mult=ln(5)*2.2/(0.001*65+2.2)=1.563251,
        # delta=20*1.563251*(1-0.592466)=12.741551
        self.assertTrue(approx(diag["p_home_before"], 0.592466))
        self.assertTrue(approx(diag["mov_multiplier"], 1.563251))
        self.assertTrue(approx(diag["delta"], 12.741551))
        self.assertTrue(approx(t.rating("A"), 1512.741551))
        self.assertTrue(approx(t.rating("B"), 1487.258449))

    def test_second_game_hand_computed(self):
        t = elo.EloRatings("nfl")
        t.update_game("A", "B", 24, 20)
        diag = t.update_game("B", "A", 10, 7)
        # B home: pre-game 1487.258449+65 vs 1512.741551 -> p=0.556625,
        # elo_diff=39.516898, mult=1.361833, delta=12.076041
        self.assertTrue(approx(diag["p_home_before"], 0.556625))
        self.assertTrue(approx(diag["mov_multiplier"], 1.361833))
        self.assertTrue(approx(diag["delta"], 12.076041))
        self.assertTrue(approx(t.rating("B"), 1499.334490))
        self.assertTrue(approx(t.rating("A"), 1500.665510))

    def test_zero_sum(self):
        t = elo.EloRatings("nfl")
        t.update_game("A", "B", 24, 20)
        t.update_game("B", "A", 10, 7)
        t.update_game("C", "D", 30, 30)  # tie
        total = sum(t.ratings.values())
        self.assertTrue(approx(total, 4 * 1500.0))

    def test_tie_uses_plain_k(self):
        t = elo.EloRatings("nfl")
        diag = t.update_game("A", "B", 20, 20)
        self.assertEqual(diag["mov_multiplier"], 1.0)
        # delta = 20 * 1 * (0.5 - 0.592466) = -1.849325
        self.assertTrue(approx(diag["delta"], -1.849325))

    def test_upset_moves_more_than_favorite_win(self):
        fav = elo.EloRatings("nfl")
        fav.ratings["f"] = 1700.0
        fav.ratings["d"] = 1500.0
        d_fav = fav.update_game("f", "d", 30, 20)["delta"]
        dog = elo.EloRatings("nfl")
        dog.ratings["f"] = 1700.0
        dog.ratings["d"] = 1500.0
        d_dog = abs(dog.update_game("d", "f", 30, 20)["delta"])
        # mov_mult for upset (2.637685) > favorite win (2.198071)
        self.assertGreater(d_dog, abs(d_fav))

    def test_mlb_no_mov(self):
        t = elo.EloRatings("mlb")
        diag = t.update_game("A", "B", 10, 1)  # blowout
        self.assertEqual(diag["mov_multiplier"], 1.0)
        # delta = 5 * (1 - p), p = 1/(1+10^(-25/400)) = 0.535915927
        self.assertTrue(approx(diag["delta"], 2.320420365))

    def test_offseason_regression(self):
        t = elo.EloRatings("nfl")
        t.update_game("A", "B", 24, 20, season="2024")
        before = t.rating("A")
        t.update_game("A", "C", 24, 20, season="2025")
        # regression applied once at the season boundary:
        # 1500 + (before - 1500) * 0.67, then game 2's update on top.
        regressed = 1500 + (before - 1500) * 0.67
        self.assertNotAlmostEqual(t.rating("A"), before)
        self.assertGreater(t.rating("A"), regressed)  # won game 2 after regressing

    def test_regress_offseason_direct(self):
        t = elo.EloRatings("nfl")
        t.ratings["a"] = 1600.0
        t.regress_offseason()
        self.assertTrue(approx(t.ratings["a"], 1567.0))

    def test_new_team_starts_at_1500(self):
        t = elo.EloRatings("nfl")
        self.assertEqual(t.rating("Expansion FC"), 1500.0)
        # unknown home team gets HFA: 1/(1+10^(-65/400)) = 0.592466
        self.assertTrue(approx(t.prob_home("Expansion FC", "A"), 0.592466))

    def test_bad_inputs_fail_closed(self):
        t = elo.EloRatings("nfl")
        with self.assertRaises(elo.EloError):
            elo.EloRatings("cbb")
        with self.assertRaises(elo.EloError):
            t.update_game("A", "B", -1, 20)
        with self.assertRaises(elo.EloError):
            t.update_game("A", "B", "x", 20)
        with self.assertRaises(elo.EloError):
            t.rating("")


class TestEloBaselineAdapter(unittest.TestCase):
    GAMES = {
        "g1": {"kickoff": "2024-09-05T23:20:00+00:00",
               "home_team": "Kansas City Chiefs", "away_team": "Baltimore Ravens",
               "home_score": 27, "away_score": 20, "season": "2024"},
        "g2": {"kickoff": "2024-09-08T17:00:00+00:00",
               "home_team": "Buffalo Bills", "away_team": "Arizona Cardinals",
               "home_score": 34, "away_score": 28, "season": "2024"},
        # future game: must never leak into earlier predictions
        "g3": {"kickoff": "2024-09-16T00:20:00+00:00",
               "home_team": "Kansas City Chiefs", "away_team": "Cincinnati Bengals",
               "home_score": 10, "away_score": 40, "season": "2024"},
    }

    def test_probability_chronological_no_leak(self):
        adapter = elo.EloBaseline("nfl")
        games = [self.GAMES["g1"], self.GAMES["g2"], self.GAMES["g3"]]
        # as_of between g2 and g3: g3 is silently excluded (point-in-time)
        p = adapter.probability(games, "Kansas City Chiefs", "Buffalo Bills",
                                "2024-09-10T00:00:00+00:00")
        self.assertTrue(0.0 < p < 1.0)
        # KC won big in g1 and BUF won small in g2; KC should be favored
        self.assertGreater(p, 0.5)
        # same call with only g1,g2 must match exactly (no leak dependence)
        p2 = adapter.probability([self.GAMES["g1"], self.GAMES["g2"]],
                                 "Kansas City Chiefs", "Buffalo Bills",
                                 "2024-09-10T00:00:00+00:00")
        self.assertEqual(p, p2)

    def test_future_games_excluded_not_raised(self):
        # A train game at/after as_of is excluded point-in-time; the
        # splitter (not this filter) owns the train/test boundary.
        adapter = elo.EloBaseline("nfl")
        p = adapter.probability(
            [self.GAMES["g1"], self.GAMES["g3"]],
            "Kansas City Chiefs", "Buffalo Bills",
            "2024-09-10T00:00:00+00:00")
        p_expected = adapter.probability(
            [self.GAMES["g1"]], "Kansas City Chiefs", "Buffalo Bills",
            "2024-09-10T00:00:00+00:00")
        self.assertEqual(p, p_expected)

    def test_unplayed_game_raises(self):
        adapter = elo.EloBaseline("nfl")
        bad = dict(self.GAMES["g1"])
        del bad["home_score"]
        with self.assertRaises(elo.EloError):
            adapter.probability([bad], "Kansas City Chiefs", "Buffalo Bills",
                                "2024-09-10T00:00:00+00:00")

    def test_make_elo_price_fn(self):
        price_fn = elo.make_elo_price_fn("nfl", self.GAMES)
        fixture = {"fixture_id": "fx", "home_team": "Kansas City Chiefs",
                   "away_team": "Buffalo Bills"}
        train = [{"fixture_id": "g1"}, {"fixture_id": "g2"}]
        preds = price_fn("elo", fixture, "2024-09-10T00:00:00+00:00", train)
        self.assertEqual(len(preds), 2)
        by_sel = {p["selection"]: p["model_p"] for p in preds}
        self.assertTrue(approx(by_sel["HOME"] + by_sel["AWAY"], 1.0))
        self.assertTrue(all(p["market"] == "ML" for p in preds))
        # wrong model name / missing teams fail closed
        with self.assertRaises(elo.EloError):
            price_fn("candidate", fixture, "2024-09-10T00:00:00+00:00", train)
        with self.assertRaises(elo.EloError):
            price_fn("elo", {"fixture_id": "fx"},
                     "2024-09-10T00:00:00+00:00", train)
        with self.assertRaises(elo.EloError):
            price_fn("elo", fixture, "2024-09-10T00:00:00+00:00",
                     [{"fixture_id": "nope"}])

    def test_naive_price_fn(self):
        preds = elo.naive_price_fn(
            "naive", {"fixture_id": "fx"}, "2024-09-10T00:00:00+00:00", [])
        self.assertEqual(
            [(p["selection"], p["model_p"]) for p in preds],
            [("HOME", 0.5), ("AWAY", 0.5)])
        with self.assertRaises(elo.EloError):
            elo.naive_price_fn("elo", {}, "2024-09-10T00:00:00+00:00", [])


class TestSeasonReplaySmoke(unittest.TestCase):
    """4-team double round-robin: invariants over a full replay."""

    TEAMS = ["Alpha", "Bravo", "Charlie", "Delta"]

    def _season_games(self):
        games = []
        day = 1
        for i, h in enumerate(self.TEAMS):
            for j, a in enumerate(self.TEAMS):
                if i == j:
                    continue
                # deterministic scores: stronger index wins at home usually
                hs = 24 + (i - j)
                aws = 20
                games.append({
                    "kickoff": "2024-09-%02dT17:00:00+00:00" % day,
                    "home_team": h, "away_team": a,
                    "home_score": max(hs, 0), "away_score": aws,
                    "season": "2024",
                })
                day += 1
        return games

    def test_replay_invariants(self):
        games = self._season_games()
        self.assertEqual(len(games), 12)
        table = elo.EloRatings("nfl")
        for g in games:
            diag = table.update_game(g["home_team"], g["away_team"],
                                     g["home_score"], g["away_score"],
                                     season=g["season"])
            self.assertTrue(0.0 < diag["p_home_before"] < 1.0)
            self.assertTrue(math.isfinite(diag["delta"]))
        # zero-sum: no inflation over the season
        self.assertTrue(
            abs(sum(table.ratings.values()) - 4 * 1500.0) < 1e-6)
        # Higher-index teams win by bigger home margins, so ratings order
        # monotonically follows team strength by construction.
        ordered = sorted(table.ratings, key=table.ratings.get, reverse=True)
        self.assertEqual(ordered, ["delta", "charlie", "bravo", "alpha"])
        # determinism: replay gives identical ratings
        table2 = elo.EloRatings("nfl")
        for g in games:
            table2.update_game(g["home_team"], g["away_team"],
                               g["home_score"], g["away_score"],
                               season=g["season"])
        self.assertEqual(table.ratings, table2.ratings)


class TestRunnerWiring(unittest.TestCase):
    def test_elo_and_naive_as_models(self):
        games = {
            "g1": {"kickoff": "2024-09-05T23:20:00+00:00",
                   "home_team": "Kansas City Chiefs",
                   "away_team": "Baltimore Ravens",
                   "home_score": 27, "away_score": 20, "season": "2024"},
            "g2": {"kickoff": "2024-09-08T17:00:00+00:00",
                   "home_team": "Buffalo Bills",
                   "away_team": "Arizona Cardinals",
                   "home_score": 34, "away_score": 28, "season": "2024"},
            "g3": {"kickoff": "2024-09-12T00:15:00+00:00",
                   "home_team": "Miami Dolphins",
                   "away_team": "Buffalo Bills",
                   "home_score": 10, "away_score": 31, "season": "2024"},
        }
        elo_fn = elo.make_elo_price_fn("nfl", games)

        def price_fn(model, fixture, as_of, train):
            if model in ("elo", "naive"):
                fn = elo_fn if model == "elo" else elo.naive_price_fn
                return fn(model, fixture, as_of, train)
            return [{"market": "ML", "selection": "HOME", "model_p": 0.6}]

        fixtures = []
        for fid, g in games.items():
            kickoff = g["kickoff"]
            as_of_dt = (datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
                        - timedelta(hours=2))
            fixtures.append({
                "fixture_id": fid, "kickoff": kickoff,
                "as_of": as_of_dt.isoformat(),
                "home_team": g["home_team"], "away_team": g["away_team"],
                "_hs": g["home_score"], "_aws": g["away_score"],
            })

        def settle_fn(fixture, market, selection, line):
            hs, aws = fixture["_hs"], fixture["_aws"]
            if selection == "HOME":
                return 1.0 if hs > aws else 0.0
            return 1.0 if aws > hs else 0.0

        sp = [splits.fixed_split(fixtures, "2024-09-10T00:00:00+00:00")]
        result = runner.run_backtest(
            fixtures=fixtures, splits=sp,
            models=["existing", "elo", "naive"],
            price_fn=price_fn, settle_fn=settle_fn,
            market_baseline=None)
        comp = runner.compare_models(result)
        self.assertIn("elo", comp["models"])
        self.assertIn("naive", comp["models"])
        # elo trained on g1 only for the g2/g3 test block; both won at home
        # for the home sides it prices -> has predictions
        self.assertGreater(comp["models"]["elo"]["n"], 0)
        verdict = backtest_report.evaluate(
            candidate=comp["models"]["elo"],
            existing=comp["models"]["existing"],
            baseline_status=comp["baseline"]["status"],
            baseline=comp["baseline"]["summary"], min_n=1)
        md = backtest_report.to_markdown(
            verdict, extra_models={"elo": comp["models"]["elo"],
                                   "naive": comp["models"]["naive"]})
        self.assertIn("| elo |", md)
        self.assertIn("| naive |", md)
        self.assertIn("MARKET_BASELINE_MISSING", md)


if __name__ == "__main__":
    unittest.main()


class TestActionability(unittest.TestCase):
    def _records(self):
        return [
            {"status": "RESEARCH_CANDIDATE_NOT_VALIDATED"},  # actionable
            {"status": "PRICED_RESEARCH"},                   # actionable
            {"status": "WATCH_STALE_QUOTE"},                 # watch
            {"status": "WATCH_SMALL_SAMPLE"},                # watch
            {"status": "BLOCKED_INVALID"},                   # blocked
            {"status": "BLOCKED_INVALID"},                   # blocked
            {"status": "NO_MODEL_OR_MARKET"},                # blocked
            {"status": ""},                                  # blocked/MISSING_STATUS
            {},                                              # blocked/MISSING_STATUS
        ]

    def test_mixed_board(self):
        from sportsedge.backtest import report as rp
        s = rp.summarize_actionability(self._records(), run_id="demo-1")
        self.assertEqual(s["total"], 9)
        self.assertEqual(s["actionable"], {"n": 2, "pct": 22.2})
        self.assertEqual(s["watch"], {"n": 2, "pct": 22.2})
        self.assertEqual(s["blocked"]["n"], 5)
        self.assertEqual(s["blocked"]["pct"], 55.6)
        self.assertEqual(s["blocked"]["by_reason"],
                         {"BLOCKED_INVALID": 2, "MISSING_STATUS": 2,
                          "NO_MODEL_OR_MARKET": 1})
        self.assertEqual(s["run_id"], "demo-1")
        self.assertTrue(s["research_only"])

    def test_empty_run(self):
        from sportsedge.backtest import report as rp
        s = rp.summarize_actionability([])
        self.assertEqual(s["total"], 0)
        self.assertEqual(s["actionable"]["pct"], 0.0)
        self.assertEqual(s["blocked"]["by_reason"], {})

    def test_malformed_input_fails_closed(self):
        from sportsedge.backtest import report as rp
        with self.assertRaises(rp.ReportError):
            rp.summarize_actionability("not-a-list")
        with self.assertRaises(rp.ReportError):
            rp.summarize_actionability([{"status": "PRICED"}, "bogus"])

    def test_custom_priced_statuses(self):
        from sportsedge.backtest import report as rp
        s = rp.summarize_actionability(
            [{"status": "CUSTOM_PRICED"}, {"status": "WATCH_X"}],
            priced_statuses={"CUSTOM_PRICED"})
        self.assertEqual(s["actionable"]["n"], 1)
        self.assertEqual(s["watch"]["n"], 1)

    def test_json_round_trip(self):
        import json
        from sportsedge.backtest import report as rp
        s = rp.summarize_actionability(self._records(), run_id="r1",
                                       run_at="2026-10-11T19:00:00Z")
        text = rp.actionability_to_json(s)
        back = json.loads(text)
        self.assertEqual(back, s)
        with self.assertRaises(rp.ReportError):
            rp.actionability_to_json({"nope": True})

    def test_markdown(self):
        from sportsedge.backtest import report as rp
        s = rp.summarize_actionability(self._records())
        md = rp.actionability_to_markdown(s)
        self.assertIn("## Actionability: 9 selections", md)
        self.assertIn("| actionable (priced, current quote) | 2 | 22.2% |", md)
        self.assertIn("- BLOCKED_INVALID: 2", md)

    def test_to_markdown_appends_section(self):
        from sportsedge.backtest import report as rp
        verdict = rp.evaluate(
            candidate={"n": 40, "brier": 0.20, "log_loss": 0.60,
                       "mean_p": 0.5, "base_rate": 0.5},
            existing={"n": 40, "brier": 0.22, "log_loss": 0.65,
                      "mean_p": 0.5, "base_rate": 0.5},
            baseline_status="MISSING", min_n=30)
        s = rp.summarize_actionability(self._records())
        md = rp.to_markdown(verdict, actionability=s)
        self.assertIn("## Actionability: 9 selections", md)
        # absent when not passed
        md2 = rp.to_markdown(verdict)
        self.assertNotIn("Actionability", md2)
