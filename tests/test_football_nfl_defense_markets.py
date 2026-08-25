import unittest


class NFLDefenseMarketTests(unittest.TestCase):
    def _path(self, *, sacks=1, interceptions=1, simulation_id=1):
        from sportsedge.core.simulate.defense_usage import (
            DefenderUsageProfile,
            EngineBDefenseAllocator,
            TeamDefenseUsageProfile,
        )
        from sportsedge.core.simulate.drive_play import FootballPlayPath, PlayEvent

        plays = []
        play_id = 0
        clock = 850
        for _ in range(sacks):
            play_id += 1
            plays.append(PlayEvent(
                1, play_id, 1, clock, "HOME", 0, 0, 0, 0, 1, 10, 75,
                "SACK", -6, 0,
            ))
            clock -= 30
        for _ in range(interceptions):
            play_id += 1
            plays.append(PlayEvent(
                1, play_id, 1, clock, "HOME", 0, 0, 0, 0, 2, 10, 70,
                "PASS", 0, 0, pass_complete=False, turnover_type="INTERCEPTION",
            ))
            clock -= 30
        play_id += 1
        plays.append(PlayEvent(
            2, play_id, 1, clock, "AWAY", 0, 0, 0, 0, 1, 10, 60,
            "RUSH", 4, 0,
        ))

        raw = FootballPlayPath(
            "NFL_DEF_MARKET", simulation_id, "HOME", "AWAY", tuple(plays)
        )
        home = TeamDefenseUsageProfile(
            "HOME",
            (
                DefenderUsageProfile("H_LB", "HOME", "LB", True, 1, 1, 0, 1, 1),
            ),
            assist_probability=0.0,
        )
        away = TeamDefenseUsageProfile(
            "AWAY",
            (
                DefenderUsageProfile("A_EDGE", "AWAY", "EDGE", True, 1, 0, 0, 1, 0),
                DefenderUsageProfile("A_LB", "AWAY", "LB", True, 1, 1, 0, 0, 0),
                DefenderUsageProfile("A_CB", "AWAY", "CB", True, 1, 0, 0, 0, 1),
            ),
            assist_probability=0.0,
        )
        return EngineBDefenseAllocator(home, away, seed=simulation_id).attribute(raw)

    def test_player_sack_market_uses_attributed_paths(self):
        from sportsedge.core.simulate.defense_markets import derive_defender_stat_market

        paths = [self._path(sacks=1, simulation_id=1), self._path(sacks=2, simulation_id=2)]
        result = derive_defender_stat_market(
            paths, player_id="A_EDGE", stat="player_sacks", line=1.5
        )
        self.assertEqual(result, {"over": 0.5, "under": 0.5, "push": 0.0})

    def test_player_interception_count_market_preserves_pushes(self):
        from sportsedge.core.simulate.defense_markets import derive_defender_stat_market

        paths = [self._path(interceptions=1, simulation_id=1), self._path(interceptions=1, simulation_id=2)]
        result = derive_defender_stat_market(
            paths, player_id="A_CB", stat="player_interceptions", line=1.0
        )
        self.assertEqual(result, {"over": 0.0, "under": 0.0, "push": 1.0})

    def test_tackles_assists_requires_explicit_settlement_provider(self):
        from sportsedge.core.simulate.defense_markets import derive_defender_stat_market

        paths = [self._path(simulation_id=1)]
        with self.assertRaisesRegex(ValueError, "TACKLE_SETTLEMENT_PROVIDER_REQUIRED"):
            derive_defender_stat_market(
                paths, player_id="A_EDGE", stat="tackles_assists", line=0.5
            )
        result = derive_defender_stat_market(
            paths,
            player_id="A_EDGE",
            stat="tackles_assists",
            line=0.5,
            tackle_settlement_provider="PROVIDER_TEST",
        )
        self.assertEqual(result["over"], 1.0)

    def test_team_sacks_and_team_turnovers_are_same_path_counts(self):
        from sportsedge.core.simulate.defense_markets import derive_team_defense_stat_market

        paths = [self._path(sacks=1, interceptions=1, simulation_id=1), self._path(sacks=2, interceptions=0, simulation_id=2)]
        sacks = derive_team_defense_stat_market(paths, team="AWAY", stat="team_sacks", line=1.5)
        turnovers = derive_team_defense_stat_market(paths, team="AWAY", stat="team_turnovers", line=0.5)
        self.assertEqual(sacks, {"over": 0.5, "under": 0.5, "push": 0.0})
        self.assertEqual(turnovers, {"over": 0.5, "under": 0.5, "push": 0.0})

    def test_unknown_player_team_and_stat_fail_closed(self):
        from sportsedge.core.simulate.defense_markets import derive_defender_stat_market, derive_team_defense_stat_market

        paths = [self._path()]
        with self.assertRaisesRegex(ValueError, "DEFENDER_NOT_IN_USAGE_TREE"):
            derive_defender_stat_market(paths, player_id="NOPE", stat="player_sacks", line=0.5)
        with self.assertRaisesRegex(ValueError, "DEFENSE_TEAM_NOT_IN_GAME"):
            derive_team_defense_stat_market(paths, team="NOPE", stat="team_sacks", line=0.5)
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_DEFENDER_STAT"):
            derive_defender_stat_market(paths, player_id="A_EDGE", stat="pressures", line=2.5)


if __name__ == "__main__":
    unittest.main()
