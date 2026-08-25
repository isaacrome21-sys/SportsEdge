import unittest

from sportsedge.core.simulate.football_path import FootballPathSimulator, TeamPlayProfile


class FootballEngineATurnoverOnDownsTests(unittest.TestCase):
    def test_failed_fourth_down_terminates_drive_without_fifth_down(self):
        low_gain = TeamPlayProfile(
            pass_rate=0.0,
            completion_rate=0.0,
            sack_rate=0.0,
            interception_rate=0.0,
            fumble_rate=0.0,
            run_yards_mean=0.1,
            run_yards_sd=0.05,
            completion_yards_mean=1.0,
            completion_yards_sd=0.1,
            pace_seconds_mean=20.0,
            field_goal_make_prob=0.0,
        )
        sim = FootballPathSimulator(
            game_id="downs-test",
            home_team="HOME",
            away_team="AWAY",
            home_profile=low_gain,
            away_profile=low_gain,
            seed=2026082401,
        )
        paths = sim.simulate(8)
        events = [event for path in paths for event in path.plays]
        self.assertTrue(any(event.drive_terminal == "TURNOVER_ON_DOWNS" for event in events))
        self.assertTrue(all(1 <= event.down <= 4 for event in events))


if __name__ == "__main__":
    unittest.main()
