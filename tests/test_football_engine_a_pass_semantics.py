import unittest


class FootballEngineAPassSemanticsTests(unittest.TestCase):
    def test_pass_play_requires_explicit_completion_state(self):
        from sportsedge.core.simulate.drive_play import PlayEvent

        with self.assertRaisesRegex(ValueError, "PASS_COMPLETION_STATE_REQUIRED"):
            PlayEvent(
                drive_id=1, play_id=1, quarter=1, clock_seconds_remaining=800,
                possession="HOME", score_before_home=0, score_before_away=0,
                score_after_home=0, score_after_away=0, down=1, distance=10,
                yardline_100=75, play_type="PASS", yards=0, points=0,
            )

    def test_incomplete_pass_cannot_carry_yards_or_score(self):
        from sportsedge.core.simulate.drive_play import PlayEvent

        with self.assertRaisesRegex(ValueError, "INCOMPLETE_PASS_STATE_INVALID"):
            PlayEvent(
                drive_id=1, play_id=1, quarter=1, clock_seconds_remaining=800,
                possession="HOME", score_before_home=0, score_before_away=0,
                score_after_home=0, score_after_away=0, down=1, distance=10,
                yardline_100=75, play_type="PASS", yards=8, points=0,
                pass_complete=False,
            )

    def test_interception_is_an_incomplete_pass_attempt(self):
        from sportsedge.core.simulate.drive_play import PlayEvent

        play = PlayEvent(
            drive_id=1, play_id=1, quarter=1, clock_seconds_remaining=800,
            possession="HOME", score_before_home=0, score_before_away=0,
            score_after_home=0, score_after_away=0, down=2, distance=7,
            yardline_100=60, play_type="PASS", yards=0, points=0,
            pass_complete=False, turnover_type="INTERCEPTION",
        )
        self.assertFalse(play.pass_complete)
        self.assertEqual(play.turnover_type, "INTERCEPTION")

    def test_non_pass_play_cannot_carry_completion_state(self):
        from sportsedge.core.simulate.drive_play import PlayEvent

        with self.assertRaisesRegex(ValueError, "NON_PASS_COMPLETION_STATE_INVALID"):
            PlayEvent(
                drive_id=1, play_id=1, quarter=1, clock_seconds_remaining=800,
                possession="HOME", score_before_home=0, score_before_away=0,
                score_after_home=0, score_after_away=0, down=1, distance=10,
                yardline_100=75, play_type="RUSH", yards=4, points=0,
                pass_complete=True,
            )

    def test_generator_tags_every_pass_and_keeps_incompletions_at_zero_yards(self):
        from sportsedge.core.simulate.drive_play import EngineADrivePlaySimulator, TeamDriveProfile

        paths = EngineADrivePlaySimulator(
            game_id="NFL_TEST", home_team="HOME", away_team="AWAY",
            home_profile=TeamDriveProfile(), away_profile=TeamDriveProfile(), seed=20260825,
        ).simulate(100)
        pass_plays = [play for path in paths for play in path.plays if play.play_type == "PASS"]
        self.assertTrue(pass_plays)
        self.assertTrue(all(play.pass_complete is not None for play in pass_plays))
        self.assertTrue(all(
            play.yards == 0 and play.points == 0
            for play in pass_plays
            if play.pass_complete is False and play.turnover_type != "INTERCEPTION"
        ))
        self.assertTrue(all(
            play.pass_complete is None
            for path in paths for play in path.plays if play.play_type != "PASS"
        ))

    def test_completion_rate_is_a_validated_profile_rate(self):
        from sportsedge.core.simulate.drive_play import TeamDriveProfile

        self.assertAlmostEqual(TeamDriveProfile().completion_rate, 0.64)
        with self.assertRaisesRegex(ValueError, "completion_rate"):
            TeamDriveProfile(completion_rate=1.01)


if __name__ == "__main__":
    unittest.main()
