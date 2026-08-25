import unittest


class NFLHalftimeRegressionTests(unittest.TestCase):
    def test_post_halftime_drive_does_not_retrigger_halftime_boundary(self):
        from sportsedge.core.simulate.drive_play import TeamDriveProfile
        from sportsedge.core.simulate.field_position import NFLFieldPositionProfile
        from sportsedge.core.simulate.regulation_simulator import NFLIntegratedRegulationSimulator
        from sportsedge.core.simulate.special_teams import SpecialTeamsProfile

        drive = TeamDriveProfile(
            pass_rate=0.55,
            completion_rate=0.64,
            success_rate=0.45,
            explosive_rate=0.10,
            turnover_rate=0.02,
            field_goal_attempt_rate=0.85,
            pace_seconds_mean=31.0,
        )
        home_special = SpecialTeamsProfile(
            team="HOME",
            kicker_id="H_K",
            kicker_active=True,
            fg_base_skill=0.86,
            xp_make_rate=0.94,
            two_point_attempt_rate=0.0,
        )
        away_special = SpecialTeamsProfile(
            team="AWAY",
            kicker_id="A_K",
            kicker_active=True,
            fg_base_skill=0.86,
            xp_make_rate=0.94,
            two_point_attempt_rate=0.0,
        )
        home_field = NFLFieldPositionProfile(
            team="HOME",
            deep_touchback_rate=1.0,
            landing_touchback_rate=0.0,
            kickoff_return_yards_sd=0.0,
            punt_net_yards_sd=0.0,
        )
        away_field = NFLFieldPositionProfile(
            team="AWAY",
            deep_touchback_rate=1.0,
            landing_touchback_rate=0.0,
            kickoff_return_yards_sd=0.0,
            punt_net_yards_sd=0.0,
        )

        result = NFLIntegratedRegulationSimulator(
            game_id="NFL_HALFTIME_REGRESSION",
            home_team="HOME",
            away_team="AWAY",
            home_profile=drive,
            away_profile=drive,
            home_special_teams=home_special,
            away_special_teams=away_special,
            home_field_position=home_field,
            away_field_position=away_field,
            seed=20260825,
        ).simulate()

        halftime = [
            transition
            for transition in result.transitions
            if transition.transition_type.startswith("HALFTIME_KICKOFF")
        ]
        self.assertEqual(len(halftime), 1)
        self.assertTrue(any(play.quarter == 3 for play in result.raw_path.plays))


if __name__ == "__main__":
    unittest.main()
