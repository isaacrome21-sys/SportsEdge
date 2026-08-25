import unittest


class FootballEngineCSpecialTeamsTests(unittest.TestCase):
    def _raw_path(self):
        from sportsedge.core.simulate.drive_play import FootballPlayPath, PlayEvent

        return FootballPlayPath(
            game_id="NFL_TEST",
            simulation_id=1,
            home_team="HOME",
            away_team="AWAY",
            plays=(
                PlayEvent(
                    drive_id=1,
                    play_id=1,
                    quarter=1,
                    clock_seconds_remaining=800,
                    possession="HOME",
                    score_before_home=0,
                    score_before_away=0,
                    score_after_home=6,
                    score_after_away=0,
                    down=1,
                    distance=5,
                    yardline_100=5,
                    play_type="PASS",
                    yards=5,
                    points=6,
                    score_type="TOUCHDOWN_CANDIDATE",
                    pass_complete=True,
                ),
                PlayEvent(
                    drive_id=2,
                    play_id=2,
                    quarter=2,
                    clock_seconds_remaining=400,
                    possession="AWAY",
                    score_before_home=6,
                    score_before_away=0,
                    score_after_home=6,
                    score_after_away=0,
                    down=4,
                    distance=4,
                    yardline_100=23,
                    play_type="FIELD_GOAL",
                    yards=0,
                    points=0,
                    score_type="FIELD_GOAL_ATTEMPT_CANDIDATE",
                    kick_distance=40,
                ),
            ),
        )

    def test_engine_a_td_is_six_points_and_field_goal_attempt_is_unresolved(self):
        path = self._raw_path()
        row = path.to_scoring_path().to_market_row()
        self.assertEqual(row["home_score"], 6)
        self.assertEqual(row["away_score"], 0)
        fg = path.plays[1]
        self.assertEqual(fg.play_type, "FIELD_GOAL")
        self.assertEqual(fg.points, 0)
        self.assertEqual(fg.score_before_away, fg.score_after_away)

    def test_engine_c_owns_xp_and_field_goal_resolution(self):
        from sportsedge.core.simulate.special_teams import (
            EngineCSpecialTeamsResolver,
            SpecialTeamsProfile,
        )

        resolved = EngineCSpecialTeamsResolver(
            home_profile=SpecialTeamsProfile(
                team="HOME",
                kicker_id="H_K",
                kicker_active=True,
                fg_base_skill=1.0,
                xp_make_rate=1.0,
                two_point_attempt_rate=0.0,
                two_point_success_rate=0.0,
            ),
            away_profile=SpecialTeamsProfile(
                team="AWAY",
                kicker_id="A_K",
                kicker_active=True,
                fg_base_skill=1.0,
                xp_make_rate=1.0,
                two_point_attempt_rate=0.0,
                two_point_success_rate=0.0,
            ),
            seed=7,
        ).resolve(self._raw_path())

        resolved.assert_reconciliation()
        row = resolved.to_scoring_path().to_market_row()
        self.assertEqual(row["home_score"], 7)
        self.assertEqual(row["away_score"], 3)
        self.assertEqual([event.event_type for event in resolved.special_teams_events], ["XP_MADE", "FG_MADE"])
        self.assertEqual(sum(event.points for event in resolved.special_teams_events), 4)

    def test_two_point_choice_replaces_xp_without_double_counting(self):
        from sportsedge.core.simulate.special_teams import (
            EngineCSpecialTeamsResolver,
            SpecialTeamsProfile,
        )

        resolved = EngineCSpecialTeamsResolver(
            home_profile=SpecialTeamsProfile(
                team="HOME",
                kicker_id="H_K",
                kicker_active=True,
                fg_base_skill=1.0,
                xp_make_rate=1.0,
                two_point_attempt_rate=1.0,
                two_point_success_rate=1.0,
            ),
            away_profile=SpecialTeamsProfile(
                team="AWAY",
                kicker_id="A_K",
                kicker_active=True,
                fg_base_skill=0.0,
                xp_make_rate=1.0,
                two_point_attempt_rate=0.0,
                two_point_success_rate=0.0,
            ),
            seed=3,
        ).resolve(self._raw_path())

        home_events = [event for event in resolved.special_teams_events if event.team == "HOME"]
        self.assertEqual(len(home_events), 1)
        self.assertEqual(home_events[0].event_type, "TWO_POINT_MADE")
        self.assertEqual(home_events[0].points, 2)
        self.assertEqual(resolved.to_scoring_path().to_market_row()["home_score"], 8)

    def test_unresolved_kicker_status_blocks_kick_opportunity(self):
        from sportsedge.core.simulate.special_teams import (
            EngineCSpecialTeamsResolver,
            SpecialTeamsProfile,
        )

        resolver = EngineCSpecialTeamsResolver(
            home_profile=SpecialTeamsProfile(team="HOME", kicker_id="H_K", kicker_active=None),
            away_profile=SpecialTeamsProfile(team="AWAY", kicker_id="A_K", kicker_active=True),
            seed=5,
        )
        with self.assertRaisesRegex(ValueError, "KICKER_STATUS_UNRESOLVED:H_K"):
            resolver.resolve(self._raw_path())

    def test_engine_c_is_seeded_and_market_blind(self):
        from sportsedge.core.simulate.special_teams import EngineCSpecialTeamsResolver, SpecialTeamsProfile

        home = SpecialTeamsProfile(team="HOME", kicker_id="H_K", kicker_active=True)
        away = SpecialTeamsProfile(team="AWAY", kicker_id="A_K", kicker_active=True)
        with self.assertRaisesRegex(ValueError, "EXPLICIT_SEED_REQUIRED"):
            EngineCSpecialTeamsResolver(home_profile=home, away_profile=away)
        with self.assertRaises(TypeError):
            EngineCSpecialTeamsResolver(home_profile=home, away_profile=away, seed=1, total_line=45.5)

    def test_engine_a_generator_emits_only_raw_td_points_and_unresolved_fgs(self):
        from sportsedge.core.simulate.drive_play import EngineADrivePlaySimulator, TeamDriveProfile

        paths = EngineADrivePlaySimulator(
            game_id="NFL_TEST",
            home_team="HOME",
            away_team="AWAY",
            home_profile=TeamDriveProfile(),
            away_profile=TeamDriveProfile(),
            seed=20260825,
        ).simulate(100)
        scoring_plays = [play for path in paths for play in path.plays if play.points]
        fg_attempts = [play for path in paths for play in path.plays if play.play_type == "FIELD_GOAL"]
        self.assertTrue(scoring_plays)
        self.assertTrue(fg_attempts)
        self.assertTrue(all(play.points == 6 for play in scoring_plays))
        self.assertTrue(all(play.points == 0 for play in fg_attempts))
        self.assertTrue(all(play.score_type == "FIELD_GOAL_ATTEMPT_CANDIDATE" for play in fg_attempts))


if __name__ == "__main__":
    unittest.main()
