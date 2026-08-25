import unittest


class FootballPlayerMarketReadoutTests(unittest.TestCase):
    def _usage(self):
        from sportsedge.core.simulate.usage import PlayerUsageProfile, TeamUsageProfile

        home = TeamUsageProfile(
            team="HOME",
            players=(
                PlayerUsageProfile("H_QB", "HOME", "QB", True, 1.0, 0.0, 0.0, 0.0, 0.1),
                PlayerUsageProfile("H_WR", "HOME", "WR", True, 1.0, 1.0, 1.0, 0.0, 0.6),
                PlayerUsageProfile("H_RB", "HOME", "RB", True, 1.0, 0.0, 0.0, 1.0, 0.4),
            ),
            quarterback_id="H_QB",
        )
        away = TeamUsageProfile(
            team="AWAY",
            players=(
                PlayerUsageProfile("A_QB", "AWAY", "QB", True, 1.0, 0.0, 0.0, 0.0, 0.1),
                PlayerUsageProfile("A_WR", "AWAY", "WR", True, 1.0, 1.0, 1.0, 0.0, 0.6),
                PlayerUsageProfile("A_RB", "AWAY", "RB", True, 1.0, 0.0, 0.0, 1.0, 0.4),
            ),
            quarterback_id="A_QB",
        )
        return home, away

    def _attributed(self, pass_yards, rush_yards, simulation_id):
        from sportsedge.core.simulate.drive_play import FootballPlayPath, PlayEvent
        from sportsedge.core.simulate.usage import EngineBUsageAllocator

        path = FootballPlayPath(
            game_id="NFL_TEST",
            simulation_id=simulation_id,
            home_team="HOME",
            away_team="AWAY",
            plays=(
                PlayEvent(
                    1, 1, 1, 850, "HOME", 0, 0, 0, 0, 1, 10, 75,
                    "PASS", pass_yards, 0, pass_complete=True,
                ),
                PlayEvent(
                    1, 2, 1, 810, "HOME", 0, 0, 0, 0, 1, 10,
                    max(0, min(100, 75 - pass_yards)), "RUSH", rush_yards, 0,
                ),
            ),
        )
        home, away = self._usage()
        return EngineBUsageAllocator(home, away, seed=simulation_id).attribute(path)

    def test_passing_yards_market_uses_existing_attributed_path_stats(self):
        from sportsedge.core.simulate.player_markets import derive_player_stat_market

        paths = [self._attributed(12, 5, 1), self._attributed(22, 3, 2)]
        market = derive_player_stat_market(paths, player_id="H_QB", stat="passing_yards", line=17.0)
        self.assertEqual(market, {"over": 0.5, "under": 0.5, "push": 0.0})

    def test_integer_count_lines_preserve_push_probability(self):
        from sportsedge.core.simulate.player_markets import derive_player_stat_market

        paths = [self._attributed(12, 5, 1), self._attributed(22, 3, 2)]
        market = derive_player_stat_market(paths, player_id="H_QB", stat="completions", line=1.0)
        self.assertEqual(market, {"over": 0.0, "under": 0.0, "push": 1.0})

    def test_combo_stat_is_from_same_player_path_not_marginal_convolution(self):
        from sportsedge.core.simulate.player_markets import derive_player_stat_market

        paths = [self._attributed(12, 5, 1), self._attributed(22, 3, 2)]
        market = derive_player_stat_market(paths, player_id="H_QB", stat="pass_plus_rush_yards", line=20.0)
        self.assertEqual(market, {"over": 0.5, "under": 0.5, "push": 0.0})

    def test_targets_require_explicit_settlement_provider_binding(self):
        from sportsedge.core.simulate.player_markets import derive_player_stat_market

        paths = [self._attributed(12, 5, 1)]
        with self.assertRaisesRegex(ValueError, "TARGET_SETTLEMENT_PROVIDER_REQUIRED"):
            derive_player_stat_market(paths, player_id="H_WR", stat="targets", line=0.5)
        market = derive_player_stat_market(
            paths,
            player_id="H_WR",
            stat="targets",
            line=0.5,
            target_settlement_provider="PROVIDER_TEST",
        )
        self.assertEqual(market["over"], 1.0)

    def test_inactive_or_unknown_player_fails_closed(self):
        from sportsedge.core.simulate.player_markets import derive_player_stat_market

        paths = [self._attributed(12, 5, 1)]
        with self.assertRaisesRegex(ValueError, "PLAYER_NOT_IN_USAGE_TREE"):
            derive_player_stat_market(paths, player_id="NOPE", stat="rushing_yards", line=1.5)

    def test_unsupported_stat_fails_closed(self):
        from sportsedge.core.simulate.player_markets import derive_player_stat_market

        paths = [self._attributed(12, 5, 1)]
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_PLAYER_STAT"):
            derive_player_stat_market(paths, player_id="H_QB", stat="fantasy_points", line=10.0)

    def test_empty_paths_fail_closed(self):
        from sportsedge.core.simulate.player_markets import derive_player_stat_market

        with self.assertRaisesRegex(ValueError, "ATTRIBUTED_PATHS_EMPTY"):
            derive_player_stat_market([], player_id="H_QB", stat="passing_yards", line=250.5)


if __name__ == "__main__":
    unittest.main()
