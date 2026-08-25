import unittest

from sportsedge.core.simulate.drive_play import EngineADrivePlaySimulator, TeamDriveProfile
from sportsedge.core.simulate.usage import EngineBUsageAllocator, PlayerUsageProfile, TeamUsageProfile
from sportsedge.core.simulate.player_markets import derive_player_market_readouts


class FootballEngineBMarketReadoutTests(unittest.TestCase):
    def _usage(self):
        home = TeamUsageProfile(
            team="HOME",
            players=(
                PlayerUsageProfile("H_QB", "HOME", "QB", True, 1.0, 0.0, 0.0, 0.08, 0.10),
                PlayerUsageProfile("H_WR1", "HOME", "WR", True, 0.96, 0.98, 0.55, 0.00, 0.50),
                PlayerUsageProfile("H_WR2", "HOME", "WR", False, 0.00, 0.00, 0.00, 0.00, 0.00),
                PlayerUsageProfile("H_TE", "HOME", "TE", True, 0.85, 0.90, 0.25, 0.00, 0.25),
                PlayerUsageProfile("H_RB", "HOME", "RB", True, 0.72, 0.35, 0.20, 0.92, 0.25),
            ),
            quarterback_id="H_QB",
        )
        away = TeamUsageProfile(
            team="AWAY",
            players=(
                PlayerUsageProfile("A_QB", "AWAY", "QB", True, 1.0, 0.0, 0.0, 0.07, 0.10),
                PlayerUsageProfile("A_WR1", "AWAY", "WR", True, 0.95, 0.98, 0.60, 0.00, 0.55),
                PlayerUsageProfile("A_TE", "AWAY", "TE", True, 0.82, 0.88, 0.22, 0.00, 0.25),
                PlayerUsageProfile("A_RB", "AWAY", "RB", True, 0.70, 0.32, 0.18, 0.93, 0.20),
            ),
            quarterback_id="A_QB",
        )
        return home, away

    def _ensemble(self, n=50):
        paths = EngineADrivePlaySimulator(
            game_id="NFL_B_MARKETS",
            home_team="HOME",
            away_team="AWAY",
            home_profile=TeamDriveProfile(pass_rate=0.61, completion_rate=0.66),
            away_profile=TeamDriveProfile(pass_rate=0.55, completion_rate=0.63),
            seed=8080,
        ).simulate(n)
        home, away = self._usage()
        attributed = EngineBUsageAllocator(home, away, seed=9090).attribute_many(paths)
        return paths, attributed

    def test_core_qb_and_skill_markets_are_read_from_same_ensemble(self):
        paths, attributed = self._ensemble()
        readout = derive_player_market_readouts(attributed)
        for market in (
            "passing_yards", "completions", "attempts", "passing_tds", "interceptions",
            "rush_yards", "longest_completion", "pass_plus_rush_yards",
            "rushing_yards", "receiving_yards", "receptions", "rush_attempts", "targets",
            "rush_plus_rec_yards", "longest_reception", "longest_rush",
            "anytime_td", "first_td", "two_plus_td",
        ):
            self.assertIn(market, readout)
        self.assertEqual(len(readout["passing_yards"]["H_QB"]["samples"]), len(paths))
        self.assertEqual(len(readout["receiving_yards"]["H_WR1"]["samples"]), len(paths))

    def test_declared_zero_touch_players_are_preserved_with_zero_samples(self):
        paths, attributed = self._ensemble(20)
        readout = derive_player_market_readouts(attributed)
        self.assertIn("H_WR2", readout["targets"])
        self.assertEqual(readout["targets"]["H_WR2"]["samples"], (0.0,) * len(paths))
        self.assertEqual(readout["receiving_yards"]["H_WR2"]["mean"], 0.0)
        self.assertEqual(readout["anytime_td"]["H_WR2"]["probability"], 0.0)

    def test_player_samples_reconcile_to_engine_a_team_volume_per_simulation(self):
        paths, attributed = self._ensemble(30)
        readout = derive_player_market_readouts(attributed)
        for index, path in enumerate(paths):
            home_pass_yards = sum(
                play.yards for play in path.plays
                if play.possession == "HOME" and play.play_type.upper() == "PASS" and play.pass_complete is True
            )
            self.assertEqual(readout["passing_yards"]["H_QB"]["samples"][index], float(home_pass_yards))

    def test_threshold_pricing_is_push_aware(self):
        _, attributed = self._ensemble(40)
        readout = derive_player_market_readouts(
            attributed,
            lines={
                "passing_yards": {"H_QB": 200.5},
                "receptions": {"H_WR1": 4.0},
            },
        )
        qb = readout["passing_yards"]["H_QB"]["price"]
        wr = readout["receptions"]["H_WR1"]["price"]
        self.assertAlmostEqual(qb["over"] + qb["under"] + qb["push"], 1.0)
        self.assertAlmostEqual(wr["over"] + wr["under"] + wr["push"], 1.0)

    def test_first_td_probabilities_use_ordered_engine_a_path(self):
        paths, attributed = self._ensemble(80)
        readout = derive_player_market_readouts(attributed)
        total_first_td = sum(row["probability"] for row in readout["first_td"].values())
        no_td = sum(
            not any(play.points == 7 and play.play_type.upper() in {"PASS", "RUSH"} for play in path.plays)
            for path in paths
        ) / len(paths)
        self.assertAlmostEqual(total_first_td + no_td, 1.0)

    def test_mixed_game_identity_or_roster_fails_closed(self):
        _, attributed = self._ensemble(3)
        foreign_paths = EngineADrivePlaySimulator(
            game_id="OTHER_GAME", home_team="HOME", away_team="AWAY",
            home_profile=TeamDriveProfile(), away_profile=TeamDriveProfile(), seed=12,
        ).simulate(1)
        home, away = self._usage()
        foreign = EngineBUsageAllocator(home, away, seed=13).attribute(foreign_paths[0])
        with self.assertRaisesRegex(ValueError, "PLAYER_MARKET_ENSEMBLE_IDENTITY_MISMATCH"):
            derive_player_market_readouts([attributed[0], foreign])

    def test_unknown_line_market_fails_closed(self):
        _, attributed = self._ensemble(2)
        with self.assertRaisesRegex(ValueError, "PLAYER_MARKET_LINE_UNSUPPORTED"):
            derive_player_market_readouts(attributed, lines={"fantasy_points": {"H_QB": 20.5}})


if __name__ == "__main__":
    unittest.main()
