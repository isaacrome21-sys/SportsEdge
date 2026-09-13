import unittest

from sportsedge.core.simulate.drive_play import TeamDriveProfile
from sportsedge.core.simulate.field_position import NFLFieldPositionProfile
from sportsedge.core.simulate.regulation_simulator import NFLIntegratedRegulationSimulator
from sportsedge.core.simulate.special_teams import SpecialTeamsProfile


class NFLIntegratedHalftimeTransitionRegressionTests(unittest.TestCase):
    def test_halftime_kickoff_is_consumed_by_a_third_quarter_drive(self):
        drive = TeamDriveProfile(
            pass_rate=0.55,
            completion_rate=0.64,
            success_rate=0.45,
            explosive_rate=0.10,
            turnover_rate=0.02,
            field_goal_attempt_rate=0.85,
            pace_seconds_mean=31.0,
        )
        result = NFLIntegratedRegulationSimulator(
            game_id="NFL_HALFTIME_REGRESSION",
            home_team="HOME",
            away_team="AWAY",
            home_profile=drive,
            away_profile=drive,
            home_special_teams=SpecialTeamsProfile(
                team="HOME", kicker_id="H_K", kicker_active=True,
                fg_base_skill=0.86, xp_make_rate=0.94,
                two_point_attempt_rate=0.0,
            ),
            away_special_teams=SpecialTeamsProfile(
                team="AWAY", kicker_id="A_K", kicker_active=True,
                fg_base_skill=0.86, xp_make_rate=0.94,
                two_point_attempt_rate=0.0,
            ),
            home_field_position=NFLFieldPositionProfile(
                team="HOME", deep_touchback_rate=1.0,
                landing_touchback_rate=0.0,
                kickoff_return_yards_sd=0.0, punt_net_yards_sd=0.0,
            ),
            away_field_position=NFLFieldPositionProfile(
                team="AWAY", deep_touchback_rate=1.0,
                landing_touchback_rate=0.0,
                kickoff_return_yards_sd=0.0, punt_net_yards_sd=0.0,
            ),
            seed=31,
        ).simulate()

        halftime = next(
            transition for transition in result.transitions
            if transition.transition_type.startswith("HALFTIME_KICKOFF")
        )
        first_third_quarter_play = next(
            play for play in result.raw_path.plays if play.quarter == 3
        )
        self.assertEqual(first_third_quarter_play.drive_id, halftime.next_drive_id)
        self.assertEqual(first_third_quarter_play.possession, halftime.next_possession_team)
        self.assertEqual(first_third_quarter_play.yardline_100, halftime.next_yardline_100)
        result.assert_reconciliation()


if __name__ == "__main__":
    unittest.main()
