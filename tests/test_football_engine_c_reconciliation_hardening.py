import unittest


class FootballEngineCReconciliationHardeningTests(unittest.TestCase):
    def _raw_path(self):
        from sportsedge.core.simulate.drive_play import FootballPlayPath, PlayEvent

        return FootballPlayPath(
            game_id="NFL_TEST",
            simulation_id=3,
            home_team="HOME",
            away_team="AWAY",
            plays=(
                PlayEvent(
                    1, 1, 1, 800, "HOME", 0, 0, 6, 0, 1, 5, 5,
                    "RUSH", 5, 6, score_type="TOUCHDOWN_CANDIDATE",
                ),
                PlayEvent(
                    2, 2, 2, 400, "AWAY", 6, 0, 6, 0, 4, 4, 23,
                    "FIELD_GOAL", 0, 0,
                    score_type="FIELD_GOAL_ATTEMPT_CANDIDATE", kick_distance=40,
                ),
            ),
        )

    def test_duplicate_field_goal_resolution_is_blocked(self):
        from sportsedge.core.simulate.special_teams import ResolvedFootballPath, SpecialTeamsEvent

        path = self._raw_path()
        resolved = ResolvedFootballPath(
            path,
            (
                SpecialTeamsEvent(1, 1, 800, "HOME", "XP_MADE", 1, kicker_id="H_K"),
                SpecialTeamsEvent(2, 2, 400, "AWAY", "FG_MADE", 3, kicker_id="A_K", kick_distance=40),
                SpecialTeamsEvent(2, 2, 400, "AWAY", "FG_MADE", 3, kicker_id="A_K", kick_distance=40),
            ),
        )
        with self.assertRaisesRegex(ValueError, "ENGINE_C_FIELD_GOAL_RESOLUTION_COUNT_INVALID"):
            resolved.assert_reconciliation()

    def test_duplicate_td_try_resolution_is_blocked(self):
        from sportsedge.core.simulate.special_teams import ResolvedFootballPath, SpecialTeamsEvent

        path = self._raw_path()
        resolved = ResolvedFootballPath(
            path,
            (
                SpecialTeamsEvent(1, 1, 800, "HOME", "XP_MADE", 1, kicker_id="H_K"),
                SpecialTeamsEvent(1, 1, 800, "HOME", "XP_MADE", 1, kicker_id="H_K"),
                SpecialTeamsEvent(2, 2, 400, "AWAY", "FG_MISSED", 0, kicker_id="A_K", kick_distance=40),
            ),
        )
        with self.assertRaisesRegex(ValueError, "ENGINE_C_TD_TRY_RESOLUTION_COUNT_INVALID"):
            resolved.assert_reconciliation()


if __name__ == "__main__":
    unittest.main()
