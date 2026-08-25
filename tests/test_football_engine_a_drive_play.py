import unittest


class FootballEngineADrivePlayTests(unittest.TestCase):
    def test_hand_built_play_path_reconciles_to_shared_scoring_path(self):
        from sportsedge.core.simulate.drive_play import FootballPlayPath, PlayEvent

        path = FootballPlayPath(
            game_id="NFL_TEST",
            simulation_id=1,
            home_team="HOME",
            away_team="AWAY",
            plays=(
                PlayEvent(
                    drive_id=1, play_id=1, quarter=1, clock_seconds_remaining=850,
                    possession="HOME", score_before_home=0, score_before_away=0,
                    score_after_home=0, score_after_away=0, down=1, distance=10,
                    yardline_100=75, play_type="RUSH", yards=5, points=0,
                ),
                PlayEvent(
                    drive_id=1, play_id=2, quarter=1, clock_seconds_remaining=810,
                    possession="HOME", score_before_home=0, score_before_away=0,
                    score_after_home=7, score_after_away=0, down=2, distance=5,
                    yardline_100=5, play_type="PASS", yards=5, points=7,
                    score_type="TOUCHDOWN_CANDIDATE", pass_complete=True,
                ),
                PlayEvent(
                    drive_id=2, play_id=3, quarter=1, clock_seconds_remaining=700,
                    possession="AWAY", score_before_home=7, score_before_away=0,
                    score_after_home=7, score_after_away=3, down=4, distance=7,
                    yardline_100=30, play_type="FIELD_GOAL", yards=0, points=3,
                    score_type="FIELD_GOAL_CANDIDATE",
                ),
            ),
        )
        path.assert_reconciliation()
        score_path = path.to_scoring_path()
        row = score_path.to_market_row()
        self.assertEqual(row["home_score"], 7)
        self.assertEqual(row["away_score"], 3)
        self.assertEqual(sum(event.points for event in score_path.events), 10)

    def test_score_chain_break_fails_closed(self):
        from sportsedge.core.simulate.drive_play import FootballPlayPath, PlayEvent

        plays = (
            PlayEvent(
                drive_id=1, play_id=1, quarter=1, clock_seconds_remaining=850,
                possession="HOME", score_before_home=0, score_before_away=0,
                score_after_home=7, score_after_away=0, down=1, distance=10,
                yardline_100=5, play_type="RUSH", yards=5, points=7,
                score_type="TOUCHDOWN_CANDIDATE",
            ),
            PlayEvent(
                drive_id=2, play_id=2, quarter=1, clock_seconds_remaining=700,
                possession="AWAY", score_before_home=0, score_before_away=0,
                score_after_home=0, score_after_away=0, down=1, distance=10,
                yardline_100=75, play_type="RUSH", yards=2, points=0,
            ),
        )
        with self.assertRaisesRegex(ValueError, "PLAY_SCORE_CHAIN_BROKEN"):
            FootballPlayPath("NFL_TEST", 1, "HOME", "AWAY", plays)

    def test_scoring_delta_must_match_points_and_possession(self):
        from sportsedge.core.simulate.drive_play import PlayEvent

        with self.assertRaisesRegex(ValueError, "PLAY_SCORING_DELTA_INVALID"):
            PlayEvent(
                drive_id=1, play_id=1, quarter=1, clock_seconds_remaining=800,
                possession="HOME", score_before_home=0, score_before_away=0,
                score_after_home=3, score_after_away=0, down=1, distance=10,
                yardline_100=20, play_type="FIELD_GOAL", yards=0, points=7,
                score_type="TOUCHDOWN_CANDIDATE",
            )

    def test_seeded_drive_play_generator_is_reproducible_and_reconciled(self):
        from sportsedge.core.simulate.drive_play import EngineADrivePlaySimulator, TeamDriveProfile

        kwargs = dict(
            game_id="NFL_TEST", home_team="HOME", away_team="AWAY",
            home_profile=TeamDriveProfile(), away_profile=TeamDriveProfile(), seed=20260824,
        )
        first = EngineADrivePlaySimulator(**kwargs).simulate(25)
        second = EngineADrivePlaySimulator(**kwargs).simulate(25)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 25)
        self.assertTrue(all(path.plays for path in first))
        for path in first:
            path.assert_reconciliation()
            row = path.to_scoring_path().to_market_row()
            if path.plays:
                last = path.plays[-1]
                self.assertEqual(row["home_score"], last.score_after_home)
                self.assertEqual(row["away_score"], last.score_after_away)

    def test_generated_scores_only_change_on_tagged_scoring_plays(self):
        from sportsedge.core.simulate.drive_play import EngineADrivePlaySimulator, TeamDriveProfile

        paths = EngineADrivePlaySimulator(
            game_id="NFL_TEST", home_team="HOME", away_team="AWAY",
            home_profile=TeamDriveProfile(), away_profile=TeamDriveProfile(), seed=91,
        ).simulate(100)
        scoring = [play for path in paths for play in path.plays if play.points]
        self.assertTrue(scoring)
        self.assertTrue(all(play.points in {3, 7} for play in scoring))
        self.assertTrue(all(play.score_type for play in scoring))
        self.assertTrue(all(
            (play.score_after_home - play.score_before_home)
            + (play.score_after_away - play.score_before_away) == play.points
            for play in scoring
        ))

    def test_generator_remains_market_blind_and_requires_explicit_seed(self):
        from sportsedge.core.simulate.drive_play import EngineADrivePlaySimulator, TeamDriveProfile

        base = dict(
            game_id="NFL_TEST", home_team="HOME", away_team="AWAY",
            home_profile=TeamDriveProfile(), away_profile=TeamDriveProfile(),
        )
        with self.assertRaisesRegex(ValueError, "EXPLICIT_SEED_REQUIRED"):
            EngineADrivePlaySimulator(**base)
        with self.assertRaises(TypeError):
            EngineADrivePlaySimulator(**base, seed=7, spread_line=-3.0)


if __name__ == "__main__":
    unittest.main()
