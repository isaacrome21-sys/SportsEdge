import unittest


class NFLFullGameDefenseTests(unittest.TestCase):
    def _profiles(self):
        from sportsedge.core.simulate.defense_usage import DefenderUsageProfile, TeamDefenseUsageProfile

        def profile(team, prefix):
            return TeamDefenseUsageProfile(
                team=team,
                players=(
                    DefenderUsageProfile(f"{prefix}_EDGE", team, "EDGE", True, 1.0, 0.0, 0.0, 1.0, 0.0),
                    DefenderUsageProfile(f"{prefix}_LB", team, "LB", True, 1.0, 1.0, 0.0, 0.0, 0.0),
                    DefenderUsageProfile(f"{prefix}_S", team, "S", True, 1.0, 0.0, 1.0, 0.0, 0.0),
                    DefenderUsageProfile(f"{prefix}_CB", team, "CB", True, 1.0, 0.0, 0.0, 0.0, 1.0),
                ),
                assist_probability=0.0,
            )
        return profile("HOME", "H"), profile("AWAY", "A")

    def _resolved_regulation(self):
        from sportsedge.core.simulate.drive_play import FootballPlayPath, PlayEvent
        from sportsedge.core.simulate.special_teams import EngineCSpecialTeamsResolver, SpecialTeamsProfile

        raw = FootballPlayPath(
            "NFL_FULL_DEF",
            1,
            "HOME",
            "AWAY",
            (
                PlayEvent(1, 1, 1, 800, "HOME", 0, 0, 0, 0, 1, 10, 75, "SACK", -7, 0),
                PlayEvent(1, 2, 1, 760, "HOME", 0, 0, 6, 0, 2, 17, 82, "RUSH", 82, 6, score_type="TOUCHDOWN_CANDIDATE"),
                PlayEvent(2, 3, 4, 100, "AWAY", 6, 0, 6, 6, 1, 10, 75, "RUSH", 75, 6, score_type="TOUCHDOWN_CANDIDATE"),
            ),
        )
        resolver = EngineCSpecialTeamsResolver(
            home_profile=SpecialTeamsProfile(team="HOME", kicker_id="H_K", kicker_active=True, fg_base_skill=1.0, xp_make_rate=1.0, two_point_attempt_rate=0.0),
            away_profile=SpecialTeamsProfile(team="AWAY", kicker_id="A_K", kicker_active=True, fg_base_skill=1.0, xp_make_rate=1.0, two_point_attempt_rate=0.0),
            seed=4,
        )
        return resolver.resolve(raw)

    def _overtime(self, regulation):
        from sportsedge.core.simulate.overtime import NFLRegularSeasonOTOpportunity, settle_nfl_regular_season_overtime
        from sportsedge.core.simulate.overtime_simulator import NFLRegularSeasonOTPlay, NFLRegularSeasonOTSimulation

        plays = (
            NFLRegularSeasonOTPlay(1, 1, "HOME", 580, 1, 10, 75, "SACK", -6),
            NFLRegularSeasonOTPlay(2, 2, "AWAY", 550, 4, 5, 25, "FIELD_GOAL", 0, kick_distance=42, special_teams_points=3, special_teams_event_type="FG_MADE"),
        )
        opportunities = (
            NFLRegularSeasonOTOpportunity(1, "HOME", None, 0, 580, "TURNOVER_ON_DOWNS"),
            NFLRegularSeasonOTOpportunity(2, "AWAY", "AWAY", 3, 550, "FIELD_GOAL"),
        )
        settlement = settle_nfl_regular_season_overtime(regulation, opportunities)
        return NFLRegularSeasonOTSimulation(regulation, plays, opportunities, settlement)

    def test_full_game_sacks_include_overtime_same_player_and_team(self):
        from sportsedge.core.simulate.defense_full_game import EngineBOvertimeDefenseAllocator, FullGameDefensivePath
        from sportsedge.core.simulate.defense_usage import EngineBDefenseAllocator

        home, away = self._profiles()
        regulation = self._resolved_regulation()
        regulation_attr = EngineBDefenseAllocator(home, away, seed=1).attribute(regulation.base_path)
        overtime = self._overtime(regulation)
        overtime_attr = EngineBOvertimeDefenseAllocator(home, away, seed=2).attribute(overtime)
        full = FullGameDefensivePath(regulation_attr, overtime_attr)
        full.assert_reconciliation()

        self.assertEqual(full.player_stats()["A_EDGE"]["sacks"], 2)
        self.assertEqual(full.team_stats()["AWAY"]["team_sacks"], 2)

    def test_defensive_market_readout_uses_full_game_ledger(self):
        from sportsedge.core.simulate.defense_full_game import EngineBOvertimeDefenseAllocator, FullGameDefensivePath
        from sportsedge.core.simulate.defense_markets import derive_defender_stat_market, derive_team_defense_stat_market
        from sportsedge.core.simulate.defense_usage import EngineBDefenseAllocator

        home, away = self._profiles()
        regulation = self._resolved_regulation()
        full = FullGameDefensivePath(
            EngineBDefenseAllocator(home, away, seed=1).attribute(regulation.base_path),
            EngineBOvertimeDefenseAllocator(home, away, seed=2).attribute(self._overtime(regulation)),
        )
        player = derive_defender_stat_market([full], player_id="A_EDGE", stat="player_sacks", line=1.5)
        team = derive_team_defense_stat_market([full], team="AWAY", stat="team_sacks", line=1.5)
        self.assertEqual(player["over"], 1.0)
        self.assertEqual(team["over"], 1.0)


if __name__ == "__main__":
    unittest.main()
