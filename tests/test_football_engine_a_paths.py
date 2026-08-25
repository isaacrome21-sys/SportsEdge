import unittest

from sportsedge.core.simulate.football_path import (
    FootballPathSimulator,
    TeamPlayProfile,
    validate_game_path,
)
from sportsedge.core.simulate.markets import derive_game_markets


class FootballEngineAPathTests(unittest.TestCase):
    def _profile(self, *, pass_rate=0.56):
        return TeamPlayProfile(
            pass_rate=pass_rate,
            completion_rate=0.64,
            sack_rate=0.065,
            interception_rate=0.022,
            fumble_rate=0.012,
            run_yards_mean=4.3,
            run_yards_sd=3.6,
            completion_yards_mean=10.8,
            completion_yards_sd=7.2,
            pace_seconds_mean=28.0,
            field_goal_make_prob=0.82,
        )

    def test_every_simulated_path_conserves_quarters_halves_total_and_margin(self):
        sim = FootballPathSimulator(
            game_id="nfl-test",
            home_team="HOME",
            away_team="AWAY",
            home_profile=self._profile(pass_rate=0.58),
            away_profile=self._profile(pass_rate=0.53),
            seed=20260824,
        )
        paths = sim.simulate(64)
        self.assertEqual(len(paths), 64)
        for path in paths:
            validate_game_path(path)
            self.assertEqual(path.q1_home + path.q2_home, path.first_half_home_score)
            self.assertEqual(path.q1_away + path.q2_away, path.first_half_away_score)
            self.assertEqual(
                path.q1_home + path.q2_home + path.q3_home + path.q4_home + path.ot_home,
                path.home_score,
            )
            self.assertEqual(
                path.q1_away + path.q2_away + path.q3_away + path.q4_away + path.ot_away,
                path.away_score,
            )
            self.assertEqual(path.home_score + path.away_score, path.total)
            self.assertEqual(path.home_score - path.away_score, path.margin)
            self.assertTrue(path.plays)
            self.assertTrue(all(event.game_id == "nfl-test" for event in path.plays))
            self.assertTrue(all(event.simulation_id == path.simulation_id for event in path.plays))

    def test_points_exist_only_when_scoring_events_exist(self):
        sim = FootballPathSimulator(
            game_id="g",
            home_team="H",
            away_team="A",
            home_profile=self._profile(),
            away_profile=self._profile(),
            seed=77,
        )
        for path in sim.simulate(20):
            home_event_points = sum(e.points for e in path.plays if e.scoring_team == "H")
            away_event_points = sum(e.points for e in path.plays if e.scoring_team == "A")
            self.assertEqual(home_event_points, path.home_score)
            self.assertEqual(away_event_points, path.away_score)

    def test_halves_are_read_from_same_path_not_independent_draws(self):
        sim = FootballPathSimulator(
            game_id="g",
            home_team="H",
            away_team="A",
            home_profile=self._profile(),
            away_profile=self._profile(),
            seed=991,
        )
        paths = sim.simulate(40)
        rows = [path.as_market_row() for path in paths]
        markets = derive_game_markets(
            rows,
            spread_line=0.0,
            total_line=45.5,
            first_half_total_line=22.5,
        )
        manual_first_half_over = sum(
            (p.q1_home + p.q2_home + p.q1_away + p.q2_away) > 22.5 for p in paths
        ) / len(paths)
        self.assertAlmostEqual(markets["first_half_total"]["over"], manual_first_half_over)

    def test_simulation_is_deterministic_for_same_seed(self):
        kwargs = dict(
            game_id="g",
            home_team="H",
            away_team="A",
            home_profile=self._profile(),
            away_profile=self._profile(),
            seed=12345,
        )
        a = [p.as_market_row() for p in FootballPathSimulator(**kwargs).simulate(12)]
        b = [p.as_market_row() for p in FootballPathSimulator(**kwargs).simulate(12)]
        self.assertEqual(a, b)

    def test_invalid_profile_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "PROFILE_PROBABILITY_OUT_OF_RANGE"):
            TeamPlayProfile(
                pass_rate=1.2,
                completion_rate=0.64,
                sack_rate=0.065,
                interception_rate=0.022,
                fumble_rate=0.012,
                run_yards_mean=4.3,
                run_yards_sd=3.6,
                completion_yards_mean=10.8,
                completion_yards_sd=7.2,
                pace_seconds_mean=28.0,
                field_goal_make_prob=0.82,
            )


if __name__ == "__main__":
    unittest.main()
