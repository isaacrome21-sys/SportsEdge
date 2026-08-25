import unittest

from sportsedge.core.simulate.football_path import FootballPathSimulator, TeamPlayProfile
from sportsedge.core.simulate.football_path_markets import derive_path_readouts


class FootballPathMarketReadoutTests(unittest.TestCase):
    def _profile(self):
        return TeamPlayProfile(
            pass_rate=0.55, completion_rate=0.64, sack_rate=0.065,
            interception_rate=0.022, fumble_rate=0.012,
            run_yards_mean=4.3, run_yards_sd=3.5,
            completion_yards_mean=10.8, completion_yards_sd=7.0,
            pace_seconds_mean=27.0, field_goal_make_prob=0.82,
        )

    def _paths(self):
        return FootballPathSimulator(
            game_id="readout-test", home_team="H", away_team="A",
            home_profile=self._profile(), away_profile=self._profile(), seed=404,
        ).simulate(80)

    def test_game_half_second_half_and_quarters_are_all_same_path_partitions(self):
        paths = self._paths()
        readout = derive_path_readouts(
            paths,
            spread_line=-2.5,
            total_line=44.5,
            first_half_spread_line=-1.5,
            first_half_total_line=21.5,
            second_half_spread_line=-1.0,
            second_half_total_line=22.5,
            quarter_spread_lines={1: -0.5, 2: -0.5, 3: 0.0, 4: 0.0},
            quarter_total_lines={1: 10.5, 2: 10.5, 3: 10.5, 4: 10.5},
        )
        self.assertIn("moneyline", readout)
        self.assertIn("first_half_moneyline", readout)
        self.assertIn("second_half_moneyline", readout)
        for q in range(1, 5):
            self.assertIn(f"q{q}_moneyline", readout)
            self.assertIn(f"q{q}_spread", readout)
            self.assertIn(f"q{q}_total", readout)

        # These are direct read-outs from the exact same paths, not independent draws.
        manual_second_half_home = sum(
            (p.q3_home + p.q4_home + p.ot_home) > (p.q3_away + p.q4_away + p.ot_away)
            for p in paths
        ) / len(paths)
        self.assertAlmostEqual(readout["second_half_moneyline"]["home_win"], manual_second_half_home)
        manual_q1_over = sum((p.q1_home + p.q1_away) > 10.5 for p in paths) / len(paths)
        self.assertAlmostEqual(readout["q1_total"]["over"], manual_q1_over)

    def test_situational_readouts_reconcile_to_events(self):
        paths = self._paths()
        readout = derive_path_readouts(paths, race_points=(10, 20))
        self.assertIn("first_score", readout)
        self.assertIn("total_touchdowns", readout)
        self.assertIn("safety", readout)
        self.assertIn("team_turnovers", readout)
        self.assertIn("team_sacks", readout)
        self.assertIn("race_to_10", readout)
        self.assertIn("race_to_20", readout)
        manual_safety = sum(any(e.drive_terminal == "SAFETY" for e in p.plays) for p in paths) / len(paths)
        self.assertAlmostEqual(readout["safety"]["yes"], manual_safety)

    def test_alternate_lines_share_the_parent_distribution(self):
        paths = self._paths()
        readout = derive_path_readouts(
            paths,
            alternate_spreads=(-7.5, -3.5, 3.5, 7.5),
            alternate_totals=(38.5, 44.5, 50.5),
        )
        self.assertEqual(set(readout["alternate_spread"]), {-7.5, -3.5, 3.5, 7.5})
        self.assertEqual(set(readout["alternate_total"]), {38.5, 44.5, 50.5})
        # More generous home spreads cannot reduce home-cover probability.
        self.assertLessEqual(
            readout["alternate_spread"][-7.5]["home_cover"],
            readout["alternate_spread"][7.5]["home_cover"],
        )

    def test_empty_paths_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "ENGINE_A_PATHS_REQUIRED"):
            derive_path_readouts([])


if __name__ == "__main__":
    unittest.main()
