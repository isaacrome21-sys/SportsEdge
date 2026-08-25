import unittest


class NFLDefenseEventTests(unittest.TestCase):
    def _defense_profiles(self, *, unresolved=False):
        from sportsedge.core.simulate.defense_usage import DefenderUsageProfile, TeamDefenseUsageProfile

        home = TeamDefenseUsageProfile(
            team="HOME",
            players=(
                DefenderUsageProfile("H_EDGE", "HOME", "EDGE", True, 1.0, 0.0, 0.0, 1.0, 0.0),
                DefenderUsageProfile("H_LB", "HOME", "LB", True, 1.0, 1.0, 0.0, 0.0, 0.0),
                DefenderUsageProfile("H_S", "HOME", "S", True, 1.0, 0.0, 1.0, 0.0, 0.0),
                DefenderUsageProfile("H_CB", "HOME", "CB", True, 1.0, 0.0, 0.0, 0.0, 1.0),
            ),
            assist_probability=1.0,
        )
        away = TeamDefenseUsageProfile(
            team="AWAY",
            players=(
                DefenderUsageProfile("A_EDGE", "AWAY", "EDGE", True, 1.0, 0.0, 0.0, 1.0, 0.0),
                DefenderUsageProfile("A_LB", "AWAY", "LB", None if unresolved else True, 1.0, 1.0, 0.0, 0.0, 0.0),
                DefenderUsageProfile("A_S", "AWAY", "S", True, 1.0, 0.0, 1.0, 0.0, 0.0),
                DefenderUsageProfile("A_CB", "AWAY", "CB", True, 1.0, 0.0, 0.0, 0.0, 1.0),
            ),
            assist_probability=1.0,
        )
        return home, away

    def _path(self):
        from sportsedge.core.simulate.drive_play import FootballPlayPath, PlayEvent

        return FootballPlayPath(
            game_id="NFL_DEF_TEST",
            simulation_id=1,
            home_team="HOME",
            away_team="AWAY",
            plays=(
                PlayEvent(
                    1, 1, 1, 850, "HOME", 0, 0, 0, 0, 1, 10, 75,
                    "PASS", 8, 0, pass_complete=True,
                ),
                PlayEvent(
                    1, 2, 1, 815, "HOME", 0, 0, 0, 0, 2, 2, 67,
                    "SACK", -7, 0,
                ),
                PlayEvent(
                    1, 3, 1, 780, "HOME", 0, 0, 0, 0, 3, 9, 74,
                    "PASS", 0, 0, pass_complete=False, turnover_type="INTERCEPTION",
                ),
                PlayEvent(
                    2, 4, 1, 700, "AWAY", 0, 0, 0, 0, 1, 10, 60,
                    "RUSH", 4, 0,
                ),
                PlayEvent(
                    2, 5, 1, 665, "AWAY", 0, 0, 0, 0, 2, 6, 56,
                    "PASS", 0, 0, pass_complete=False,
                ),
            ),
        )

    def test_sack_profile_rate_is_bounded(self):
        from sportsedge.core.simulate.drive_play import TeamDriveProfile

        self.assertGreaterEqual(TeamDriveProfile().sack_rate, 0.0)
        with self.assertRaisesRegex(ValueError, "sack_rate"):
            TeamDriveProfile(sack_rate=1.1)

    def test_generated_sacks_are_negative_non_attempt_plays(self):
        from sportsedge.core.simulate.drive_play import EngineADrivePlaySimulator, TeamDriveProfile

        offense = TeamDriveProfile(
            pass_rate=1.0,
            completion_rate=1.0,
            success_rate=0.5,
            explosive_rate=0.0,
            turnover_rate=0.0,
            sack_rate=1.0,
            field_goal_attempt_rate=0.0,
            pace_seconds_mean=25.0,
        )
        paths = EngineADrivePlaySimulator(
            game_id="NFL_SACK_TEST",
            home_team="HOME",
            away_team="AWAY",
            home_profile=offense,
            away_profile=offense,
            seed=20260825,
        ).simulate(5)
        sacks = [play for path in paths for play in path.plays if play.play_type == "SACK"]
        self.assertTrue(sacks)
        self.assertTrue(all(play.yards < 0 for play in sacks))
        self.assertTrue(all(play.points == 0 for play in sacks))
        self.assertTrue(all(play.pass_complete is None for play in sacks))

    def test_defensive_attribution_reconciles_sacks_interceptions_and_tackles(self):
        from sportsedge.core.simulate.defense_usage import EngineBDefenseAllocator

        home, away = self._defense_profiles()
        attributed = EngineBDefenseAllocator(home, away, seed=7).attribute(self._path())
        attributed.assert_reconciliation()
        stats = attributed.player_stats()

        self.assertEqual(stats["A_EDGE"]["sacks"], 1)
        self.assertEqual(stats["A_EDGE"]["solo_tackles"], 1)
        self.assertEqual(stats["A_CB"]["interceptions"], 1)
        self.assertEqual(stats["A_LB"]["solo_tackles"], 1)
        self.assertEqual(stats["A_S"]["assists"], 2)
        self.assertEqual(stats["H_LB"]["solo_tackles"], 1)
        self.assertEqual(stats["H_S"]["assists"], 1)

        team = attributed.team_stats()
        self.assertEqual(team["AWAY"]["team_sacks"], 1)
        self.assertEqual(team["AWAY"]["team_turnovers"], 1)
        self.assertEqual(team["HOME"]["team_sacks"], 0)
        self.assertEqual(team["HOME"]["team_turnovers"], 0)

    def test_sack_and_interception_identity_live_on_the_same_a_play(self):
        from sportsedge.core.simulate.defense_usage import EngineBDefenseAllocator

        home, away = self._defense_profiles()
        attributed = EngineBDefenseAllocator(home, away, seed=7).attribute(self._path())
        sack = next(play for play in attributed.plays if play.base_play.play_type == "SACK")
        interception = next(
            play for play in attributed.plays
            if play.base_play.turnover_type == "INTERCEPTION"
        )
        self.assertEqual(sack.sack_player_id, "A_EDGE")
        self.assertEqual(sack.primary_tackler_id, "A_EDGE")
        self.assertEqual(interception.interceptor_id, "A_CB")

    def test_unresolved_defender_participation_fails_closed(self):
        from sportsedge.core.simulate.defense_usage import EngineBDefenseAllocator

        home, away = self._defense_profiles(unresolved=True)
        with self.assertRaisesRegex(ValueError, "DEFENDER_PARTICIPATION_UNRESOLVED:A_LB"):
            EngineBDefenseAllocator(home, away, seed=7).attribute(self._path())

    def test_defense_allocator_is_seeded_and_market_blind(self):
        from sportsedge.core.simulate.defense_usage import EngineBDefenseAllocator

        home, away = self._defense_profiles()
        first = EngineBDefenseAllocator(home, away, seed=19).attribute(self._path())
        second = EngineBDefenseAllocator(home, away, seed=19).attribute(self._path())
        self.assertEqual(first, second)
        with self.assertRaisesRegex(ValueError, "EXPLICIT_SEED_REQUIRED"):
            EngineBDefenseAllocator(home, away)
        with self.assertRaises(TypeError):
            EngineBDefenseAllocator(home, away, seed=1, spread_line=-3.0)


if __name__ == "__main__":
    unittest.main()
