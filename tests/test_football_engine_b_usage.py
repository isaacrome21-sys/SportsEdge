import unittest


class FootballEngineBUsageTests(unittest.TestCase):
    def _usage(self, *, unresolved=False):
        from sportsedge.core.simulate.usage import PlayerUsageProfile, TeamUsageProfile

        home = TeamUsageProfile(
            team="HOME",
            players=(
                PlayerUsageProfile("H_QB", "HOME", "QB", True, 1.0, 0.0, 0.0, 0.05, 0.10),
                PlayerUsageProfile("H_WR", "HOME", "WR", None if unresolved else True, 0.95, 0.98, 0.70, 0.00, 0.50),
                PlayerUsageProfile("H_RB", "HOME", "RB", True, 0.70, 0.35, 0.30, 0.95, 0.50),
            ),
            quarterback_id="H_QB",
        )
        away = TeamUsageProfile(
            team="AWAY",
            players=(
                PlayerUsageProfile("A_QB", "AWAY", "QB", True, 1.0, 0.0, 0.0, 0.05, 0.10),
                PlayerUsageProfile("A_WR", "AWAY", "WR", True, 0.95, 0.98, 0.75, 0.00, 0.55),
                PlayerUsageProfile("A_RB", "AWAY", "RB", True, 0.70, 0.30, 0.25, 0.95, 0.45),
            ),
            quarterback_id="A_QB",
        )
        return home, away

    def _path(self):
        from sportsedge.core.simulate.drive_play import FootballPlayPath, PlayEvent

        return FootballPlayPath(
            game_id="NFL_TEST", simulation_id=1, home_team="HOME", away_team="AWAY",
            plays=(
                PlayEvent(
                    1, 1, 1, 850, "HOME", 0, 0, 0, 0, 1, 10, 75,
                    "PASS", 12, 0, pass_complete=True,
                ),
                PlayEvent(
                    1, 2, 1, 815, "HOME", 0, 0, 0, 0, 1, 10, 63,
                    "RUSH", 5, 0,
                ),
                PlayEvent(
                    1, 3, 1, 780, "HOME", 0, 0, 7, 0, 2, 5, 5,
                    "PASS", 5, 7, score_type="TOUCHDOWN_CANDIDATE", pass_complete=True,
                ),
            ),
        )

    def test_unresolved_participation_is_input_missing_not_silent_fallback(self):
        from sportsedge.core.simulate.usage import EngineBUsageAllocator

        home, away = self._usage(unresolved=True)
        with self.assertRaisesRegex(ValueError, "PARTICIPATION_UNRESOLVED:H_WR"):
            EngineBUsageAllocator(home, away, seed=7).attribute(self._path())

    def test_single_role_tree_reconciles_qb_receiver_and_rusher_stats(self):
        from sportsedge.core.simulate.usage import EngineBUsageAllocator

        home, away = self._usage()
        attributed = EngineBUsageAllocator(home, away, seed=7).attribute(self._path())
        attributed.assert_reconciliation()
        stats = attributed.player_stats()

        self.assertEqual(stats["H_QB"]["pass_attempts"], 2)
        self.assertEqual(stats["H_QB"]["completions"], 2)
        self.assertEqual(stats["H_QB"]["passing_yards"], 17)
        self.assertEqual(stats["H_QB"]["passing_tds"], 1)
        self.assertEqual(stats["H_WR"]["targets"], 2)
        self.assertEqual(stats["H_WR"]["receptions"], 2)
        self.assertEqual(stats["H_WR"]["receiving_yards"], 17)
        self.assertEqual(stats["H_WR"]["receiving_tds"], 1)
        self.assertEqual(stats["H_RB"]["rush_attempts"], 1)
        self.assertEqual(stats["H_RB"]["rushing_yards"], 5)

    def test_td_identity_is_on_the_same_scoring_play(self):
        from sportsedge.core.simulate.usage import EngineBUsageAllocator

        home, away = self._usage()
        attributed = EngineBUsageAllocator(home, away, seed=7).attribute(self._path())
        td = [play for play in attributed.plays if play.base_play.points == 7][0]
        self.assertEqual(td.passer_id, "H_QB")
        self.assertEqual(td.receiver_id, "H_WR")
        self.assertEqual(td.touchdown_scorer_id, "H_WR")

    def test_seeded_usage_allocation_is_reproducible_on_generated_paths(self):
        from sportsedge.core.simulate.drive_play import EngineADrivePlaySimulator, TeamDriveProfile
        from sportsedge.core.simulate.usage import EngineBUsageAllocator

        home, away = self._usage()
        path = EngineADrivePlaySimulator(
            game_id="NFL_TEST", home_team="HOME", away_team="AWAY",
            home_profile=TeamDriveProfile(), away_profile=TeamDriveProfile(), seed=11,
        ).simulate(1)[0]
        first = EngineBUsageAllocator(home, away, seed=99).attribute(path)
        second = EngineBUsageAllocator(home, away, seed=99).attribute(path)
        self.assertEqual(first, second)
        first.assert_reconciliation()

    def test_receptions_never_exceed_targets_and_team_yards_reconcile(self):
        from sportsedge.core.simulate.drive_play import EngineADrivePlaySimulator, TeamDriveProfile
        from sportsedge.core.simulate.usage import EngineBUsageAllocator

        home, away = self._usage()
        paths = EngineADrivePlaySimulator(
            game_id="NFL_TEST", home_team="HOME", away_team="AWAY",
            home_profile=TeamDriveProfile(), away_profile=TeamDriveProfile(), seed=21,
        ).simulate(20)
        allocator = EngineBUsageAllocator(home, away, seed=31)
        for path in paths:
            attributed = allocator.attribute(path)
            attributed.assert_reconciliation()
            for row in attributed.player_stats().values():
                self.assertLessEqual(row["receptions"], row["targets"])

    def test_allocator_is_market_blind_and_requires_seed(self):
        from sportsedge.core.simulate.usage import EngineBUsageAllocator

        home, away = self._usage()
        with self.assertRaisesRegex(ValueError, "EXPLICIT_SEED_REQUIRED"):
            EngineBUsageAllocator(home, away)
        with self.assertRaises(TypeError):
            EngineBUsageAllocator(home, away, seed=7, spread_line=-3.0)


if __name__ == "__main__":
    unittest.main()
