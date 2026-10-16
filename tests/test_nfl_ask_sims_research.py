"""Synthetic-only tests for Ask the Sims research readout and refusals."""
import unittest

from sportsedge.sports.nfl.ask_sims import (
    AskSimsError, ask_score_paths, parse_question,
)

HOME, AWAY = "DEN", "SEA"
PATHS = [
    {"home_score": 10, "away_score": 17},
    {"home_score": 10, "away_score": 16},
    {"home_score": 35, "away_score": 10},
    {"home_score": 20, "away_score": 20},
]


class AskSimsResearchTests(unittest.TestCase):
    def ask(self, q, **kwargs):
        return ask_score_paths(PATHS, q, home_team=HOME, away_team=AWAY,
                               aliases={"Seahawks": AWAY, "Broncos": HOME}, **kwargs)

    def test_win_by_seven_counts_exact_boundary(self):
        row = self.ask("Seahawks win by 7+", price_american=180)
        self.assertEqual((row["win_count"], row["push_count"], row["loss_count"]), (1, 0, 3))
        self.assertAlmostEqual(row["sample_win_probability"], 0.25)
        self.assertAlmostEqual(row["estimated_roi_per_dollar"], -0.30)
        self.assertAlmostEqual(row["raw_implied_probability"], 1 / 2.8)
        self.assertTrue(row["sampling_interval_not_model_uncertainty"])
        self.assertEqual(row["picks"], [])
        self.assertFalse(row["eligible_as_bet"])
        self.assertEqual(row["quote_status"], "USER_SUPPLIED_UNVERIFIED")

    def test_two_way_moneyline_tie_pushes(self):
        row = self.ask("SEA wins", price_american=180)
        self.assertEqual((row["win_count"], row["push_count"], row["loss_count"]), (2, 1, 1))
        self.assertAlmostEqual(row["sample_conditional_win_probability"], 2 / 3)
        self.assertAlmostEqual(row["estimated_roi_per_dollar"], (2 * 1.8 - 1) / 4)

    def test_spread_and_correct_score_queries(self):
        row = self.ask("SEA covers -7")
        self.assertEqual((row["win_count"], row["push_count"], row["loss_count"]), (0, 1, 3))
        row = self.ask("DEN covers +7")
        self.assertEqual((row["win_count"], row["push_count"], row["loss_count"]), (3, 1, 0))
        row = self.ask("correct score 10-17")
        self.assertEqual((row["win_count"], row["push_count"], row["loss_count"]), (1, 0, 3))
        with self.assertRaisesRegex(AskSimsError, "LINE_INVALID"):
            self.ask({"market": "spread", "team": "away", "line": float("nan")})

    def test_total_and_team_total_integer_pushes(self):
        row = self.ask("total over 40", price_american=-110)
        self.assertEqual((row["win_count"], row["push_count"], row["loss_count"]), (1, 1, 2))
        self.assertAlmostEqual(row["estimated_roi_per_dollar"], (100/110 - 2)/4)
        row = self.ask("SEA team total under 16")
        self.assertEqual((row["win_count"], row["push_count"], row["loss_count"]), (1, 1, 2))

    def test_win_and_correlated_combo_from_same_paths(self):
        self.assertEqual(self.ask("SEA wins")["win_count"], 2)
        query = {"all": [{"market": "win_by", "team": "away", "points": 7},
                         {"market": "total_over", "line": 25.5}]}
        self.assertEqual(self.ask(query)["win_count"], 1)
        self.assertEqual(self.ask(query)["loss_count"], 3)

    def test_unsupported_language_and_unknown_team_refuse(self):
        with self.assertRaisesRegex(AskSimsError, "UNSUPPORTED_QUESTION"):
            self.ask("Seahawks win the coin toss")
        with self.assertRaisesRegex(AskSimsError, "TEAM_UNKNOWN"):
            self.ask("Packers win by 7+")
        with self.assertRaisesRegex(AskSimsError, "TEAM_SIDE_INVALID"):
            self.ask({"market": "win_by", "team": "SEA", "points": 7})

    def test_malformed_score_line_quote_and_identity_refuse(self):
        with self.assertRaisesRegex(AskSimsError, "SCORE_INVALID"):
            ask_score_paths([{"home_score": True, "away_score": 14}], "SEA wins",
                            home_team=HOME, away_team=AWAY)
        with self.assertRaisesRegex(AskSimsError, "LINE_INVALID"):
            self.ask({"market": "total_over", "line": float("nan")})
        with self.assertRaisesRegex(AskSimsError, "AMERICAN_PRICE_INVALID"):
            self.ask("SEA wins", price_american=-99)
        with self.assertRaisesRegex(AskSimsError, "GAME_IDENTITY_INVALID"):
            ask_score_paths(PATHS, "SEA wins", home_team="SEA", away_team="SEA")

    def test_enormous_structured_lines_refuse_without_overflow(self):
        # Python math.isfinite(10**1000) raises OverflowError; reject the
        # out-of-range value first, without changing market authority.
        huge = 10 ** 1000
        for market, line in (("total_over", huge),
                             ("team_total_under", -huge),
                             ("spread", huge), ("spread", -huge)):
            query = {"market": market, "line": line}
            if market != "total_over":
                query["team"] = "away"
            with self.subTest(market=market, sign=line > 0):
                with self.assertRaisesRegex(AskSimsError, "ASK_SIMS_LINE_INVALID"):
                    self.ask(query)

    def test_enormous_replay_means_refuse_without_overflow(self):
        from sportsedge.sports.nfl.ask_sims import ask_unified_score_sims
        from sportsedge.sports.nfl.unified_market_engine import run_unified_nfl_model
        engine = run_unified_nfl_model(
            game_id="2026_06_SEA_DEN", home_team=HOME, away_team=AWAY,
            attempt9_margin=0.0, attempt9_total=44.0, n_sims=16, seed=7,
        )
        for field in ("mean_home", "mean_away"):
            for value in (10 ** 1000, -(10 ** 1000)):
                tampered = {**engine, "score_means": {**engine["score_means"], field: value}}
                with self.subTest(field=field, positive=value > 0):
                    with self.assertRaisesRegex(AskSimsError, "ASK_SIMS_MEANS_INVALID"):
                        ask_unified_score_sims(
                            tampered, "SEA wins", home_team=HOME, away_team=AWAY,
                        )

    def test_malformed_alias_mapping_is_named_refusal(self):
        with self.assertRaisesRegex(AskSimsError, "ALIASES_INVALID"):
            ask_score_paths(PATHS, "SEA wins", home_team=HOME, away_team=AWAY,
                            aliases=["not a mapping"])

    def test_no_nonpush_paths_does_not_claim_conditional_fair_price(self):
        row = self.ask("total under 40")
        self.assertEqual(row["push_count"], 1)
        only_push = ask_score_paths([PATHS[3]], "total over 40",
                                   home_team=HOME, away_team=AWAY)
        self.assertIsNone(only_push["sample_conditional_win_probability"])
        self.assertEqual(only_push["sample_win_probability"], 0)

    def test_alias_collision_and_bad_compound_refuse(self):
        with self.assertRaisesRegex(AskSimsError, "ALIAS_COLLISION"):
            parse_question("DEN wins", home_team=HOME, away_team=AWAY,
                           aliases={"DEN": "SEA"})
        with self.assertRaisesRegex(AskSimsError, "AND_TERMS_INVALID"):
            self.ask({"all": []})



class AskSimsEngineReplayTests(unittest.TestCase):
    def test_unified_replay_matches_native_seeded_score_path(self):
        from sportsedge.sports.nfl.ask_sims import ask_unified_score_sims
        from sportsedge.sports.nfl.discrete_v2 import load_freeze, score_grid
        from sportsedge.sports.nfl.unified_market_engine import (
            run_unified_nfl_model, sample_score_paths,
        )
        engine = run_unified_nfl_model(
            game_id="2026_06_SEA_DEN", home_team=HOME, away_team=AWAY,
            attempt9_margin=0.0, attempt9_total=44.0, n_sims=128, seed=7,
        )
        result = ask_unified_score_sims(
            engine, "Seahawks win by 7+", home_team=HOME, away_team=AWAY,
            aliases={"Seahawks": AWAY},
        )
        means = engine["score_means"]
        native = sample_score_paths(
            score_grid(means["mean_home"], means["mean_away"], load_freeze()),
            n_sims=128, seed=7,
        )
        comparison = ask_score_paths(
            native, "SEA wins by 7+", home_team=HOME, away_team=AWAY,
        )
        self.assertEqual(result["win_count"], comparison["win_count"])
        self.assertEqual(result["sample_count"], 128)
        self.assertEqual(result["source_status"], "FROZEN_GRID_SEEDED_REPLAY_RESEARCH_ONLY")
        self.assertFalse(result["eligible_as_bet"])
        engine["score_distribution"]["freeze_sha256"] = "tampered"
        with self.assertRaisesRegex(AskSimsError, "FROZEN_GRID_MISMATCH"):
            ask_unified_score_sims(
                engine, "SEA wins", home_team=HOME, away_team=AWAY,
            )

if __name__ == "__main__":
    unittest.main()
