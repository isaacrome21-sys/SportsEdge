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


if __name__ == "__main__":
    unittest.main()
