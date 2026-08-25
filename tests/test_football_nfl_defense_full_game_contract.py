import unittest


class NFLDefenseFullGameContractTests(unittest.TestCase):
    def test_regulation_only_paths_remain_supported_for_regulation_scopes(self):
        from sportsedge.core.simulate.defense_usage import (
            AttributedDefensivePath,
            AttributedDefensivePlay,
            DefenderUsageProfile,
            TeamDefenseUsageProfile,
        )
        from sportsedge.core.simulate.drive_play import FootballPlayPath, PlayEvent
        from sportsedge.core.simulate.defense_markets import derive_team_defense_stat_market

        home = TeamDefenseUsageProfile("HOME", (DefenderUsageProfile("H", "HOME", "LB", True, 1, 1, 0, 0, 0),), 0)
        away = TeamDefenseUsageProfile("AWAY", (DefenderUsageProfile("A", "AWAY", "EDGE", True, 1, 1, 0, 1, 0),), 0)
        base = FootballPlayPath("G", 1, "HOME", "AWAY", (PlayEvent(1, 1, 1, 800, "HOME", 0, 0, 0, 0, 1, 10, 75, "SACK", -5),))
        attributed = AttributedDefensivePath(
            base,
            home,
            away,
            (AttributedDefensivePlay(base.plays[0], "AWAY", ("A",), primary_tackler_id="A", sack_player_id="A"),),
        )
        self.assertEqual(
            derive_team_defense_stat_market([attributed], team="AWAY", stat="team_sacks", line=0.5)["over"],
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
