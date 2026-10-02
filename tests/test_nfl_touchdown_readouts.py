from dataclasses import replace
import unittest

from sportsedge.core.simulate.football_path import FootballGamePath, ScoringEvent
from sportsedge.sports.nfl.touchdown_readouts import CompleteScorerPath, ScorerBinding, derive_touchdown_readouts


def path(sim, specs):
    events, scorers = [], {}
    for index, (period, clock, team, kind, points, player) in enumerate(specs):
        key = f"{sim}:{index}"
        events.append(ScoringEvent(key, period, clock, team, points, kind))
        if player is not None:
            scorers[key] = ScorerBinding(player, team)
    base = FootballGamePath("G", sim, "H", "A", tuple(events))
    roster = {"WR": "H", "QB": "H", "RETURNER": "A", "DB": "A"}
    return CompleteScorerPath(base, scorers, tuple(e.event_id for e in events), "FULL_GAME_INCLUDING_OVERTIME", roster)


class TouchdownReadoutsTests(unittest.TestCase):
    def run_rows(self, rows, **kwargs):
        return derive_touchdown_readouts(rows, player_id="WR", player_team="H", **kwargs)

    def sample(self):
        return [path(1, [(1, 500, "H", "TOUCHDOWN", 6, "WR"),
                         (1, 500, "H", "XP_MADE", 1, None),
                         (5, 100, "H", "TOUCHDOWN", 6, "WR")]),
                path(2, [(2, 200, "A", "FG_MADE", 3, None)])]

    def test_joint_counts_push_and_game_scores(self):
        out = self.run_rows(self.sample(), td_line=2, spread_line=-13, total_line=13)
        self.assertEqual(out["td_count_pmf"], {0: .5, 2: .5})
        self.assertEqual(out["anytime_td"], .5)
        self.assertEqual(out["two_plus_td"], .5)
        self.assertEqual(out["three_plus_td"], 0)
        self.assertEqual(out["td_total"], {"over": 0, "under": .5, "push": .5})
        self.assertEqual(out["game_markets"]["spread"]["push"], .5)
        self.assertEqual(out["game_markets"]["total"]["push"], .5)
        self.assertFalse(out["model_p_created"])
        self.assertFalse(out["official_authority"])

    def test_no_td_games_remain_in_first_last_denominator(self):
        out = self.run_rows(self.sample())
        self.assertEqual(out["first_td"], .5)
        self.assertEqual(out["last_td"], .5)
        self.assertEqual(out["no_touchdown"], .5)

    def test_defensive_and_return_touchdowns_compete_for_first_and_last(self):
        rows = [path(1, [(1, 890, "A", "KICKOFF_RETURN_TD", 6, "RETURNER"),
                         (2, 300, "H", "TOUCHDOWN", 6, "WR"),
                         (5, 20, "A", "DEFENSIVE_RETURN_TOUCHDOWN", 6, "DB")])]
        out = self.run_rows(rows)
        self.assertEqual(out["anytime_td"], 1)
        self.assertEqual(out["first_td"], 0)
        self.assertEqual(out["last_td"], 0)
        self.assertEqual(out["game_td_count_pmf"], {3: 1})

    def test_missing_return_identity_blocks_instead_of_ignoring_td(self):
        p = path(1, [(1, 890, "A", "PUNT_RETURN_TD", 6, None)])
        with self.assertRaisesRegex(ValueError, "SCORER_IDENTITY_REQUIRED"):
            self.run_rows([p])

    def test_passing_td_does_not_credit_passer(self):
        out = derive_touchdown_readouts(self.sample(), player_id="QB", player_team="H")
        self.assertEqual(out["anytime_td"], 0)

    def test_same_clock_order_uses_explicit_source_order(self):
        p = path(1, [(1, 100, "H", "TOUCHDOWN", 6, "WR"),
                     (1, 100, "A", "KICKOFF_RETURN_TD", 6, "RETURNER")])
        self.assertEqual(self.run_rows([p])["first_td"], 1)
        self.assertEqual(self.run_rows([replace(p, ordered_event_ids=tuple(reversed(p.ordered_event_ids)))])["first_td"], 0)

    def test_bad_scope_order_identity_and_duplicate_samples_fail(self):
        p = self.sample()[0]
        cases = [([replace(p, settlement_scope="REGULATION")], "SCOPE_REQUIRED"),
                 ([replace(p, ordered_event_ids=p.ordered_event_ids[:-1])], "EVENT_ORDER_REQUIRED"),
                 ([replace(p, ordered_event_ids=tuple(reversed(p.ordered_event_ids)))], "ORDER_INVALID"),
                 ([p, p], "DUPLICATE_SIMULATION"),
                 ([p, replace(self.sample()[1], path=replace(self.sample()[1].path, game_id="OTHER"))], "GAME_IDENTITY_MISMATCH")]
        for rows, error in cases:
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                self.run_rows(rows)

    def test_unknown_event_and_bundled_try_fail(self):
        for kind, points, error in [("MYSTERY", 6, "UNCLASSIFIED"), ("TOUCHDOWN", 7, "SEPARATE_TRY")]:
            with self.assertRaisesRegex(ValueError, error):
                self.run_rows([path(1, [(1, 100, "H", kind, points, "WR")])])

    def test_nonfinite_and_boolean_lines_fail(self):
        for line in [True, float("nan"), float("inf")]:
            with self.assertRaisesRegex(ValueError, "FINITE_NUMERIC"):
                self.run_rows(self.sample(), td_line=line)

    def test_unknown_player_cannot_be_treated_as_zero_probability(self):
        with self.assertRaisesRegex(ValueError, "PARTICIPATION_UNBOUND"):
            derive_touchdown_readouts(self.sample(), player_id="UNKNOWN", player_team="H")

    def test_false_field_goal_cannot_hide_a_touchdown(self):
        with self.assertRaisesRegex(ValueError, "NON_TD_POINTS_INVALID"):
            self.run_rows([path(1, [(1, 100, "H", "FG_MADE", 6, None)])])


if __name__ == "__main__":
    unittest.main()
