import unittest

from sportsedge.core.simulate.drive_play import EngineADrivePlaySimulator, TeamDriveProfile
from sportsedge.core.simulate.participation import EngineBParticipationSimulator, TeamPersonnelProfile
from sportsedge.core.simulate.participation_markets import derive_player_market_readouts


class FootballEngineBMarketTests(unittest.TestCase):
    def _personnel(self, prefix):
        return TeamPersonnelProfile(
            quarterback_id=f"{prefix}_QB",
            rush_shares=((f"{prefix}_RB1", 0.75), (f"{prefix}_RB2", 0.15), (f"{prefix}_QB", 0.10)),
            target_shares=((f"{prefix}_WR1", 0.40), (f"{prefix}_WR2", 0.25), (f"{prefix}_TE1", 0.20), (f"{prefix}_RB1", 0.15)),
        )

    def _ensemble(self, n=60):
        home_personnel = self._personnel("H")
        away_personnel = self._personnel("A")
        paths = EngineADrivePlaySimulator(
            game_id="NFL_B_MARKETS", home_team="HOME", away_team="AWAY",
            home_profile=TeamDriveProfile(pass_rate=0.61, completion_rate=0.66),
            away_profile=TeamDriveProfile(pass_rate=0.55, completion_rate=0.63),
            seed=8080,
        ).simulate(n)
        engine = EngineBParticipationSimulator(
            home_team="HOME", away_team="AWAY",
            home_personnel=home_personnel, away_personnel=away_personnel,
            seed=9090,
        )
        overlays = [engine.assign(path) for path in paths]
        return paths, overlays, home_personnel, away_personnel

    def _readout(self, n=60, **kwargs):
        paths, overlays, home_personnel, away_personnel = self._ensemble(n)
        readout = derive_player_market_readouts(
            paths,
            overlays,
            home_personnel=home_personnel,
            away_personnel=away_personnel,
            **kwargs,
        )
        return paths, overlays, readout

    def test_core_qb_and_skill_markets_are_read_from_same_simulation_ensemble(self):
        paths, _, readout = self._readout()
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

    def test_declared_zero_touch_players_remain_in_market_universe_with_zero_samples(self):
        home_personnel = TeamPersonnelProfile(
            quarterback_id="H_QB",
            rush_shares=(("H_RB", 1.0),),
            target_shares=(("H_WR_ACTIVE", 1.0), ("H_WR_ZERO", 0.0)),
        )
        away_personnel = TeamPersonnelProfile(
            quarterback_id="A_QB",
            rush_shares=(("A_RB", 1.0),),
            target_shares=(("A_WR", 1.0),),
        )
        paths = EngineADrivePlaySimulator(
            game_id="NFL_ZERO_TOUCH", home_team="HOME", away_team="AWAY",
            home_profile=TeamDriveProfile(pass_rate=0.6, completion_rate=0.65),
            away_profile=TeamDriveProfile(pass_rate=0.6, completion_rate=0.65), seed=701,
        ).simulate(10)
        engine = EngineBParticipationSimulator(
            home_team="HOME", away_team="AWAY",
            home_personnel=home_personnel, away_personnel=away_personnel, seed=702,
        )
        overlays = [engine.assign(path) for path in paths]
        readout = derive_player_market_readouts(
            paths,
            overlays,
            home_personnel=home_personnel,
            away_personnel=away_personnel,
        )
        self.assertIn("H_WR_ZERO", readout["targets"])
        self.assertEqual(readout["targets"]["H_WR_ZERO"]["samples"], (0.0,) * len(paths))
        self.assertEqual(readout["receiving_yards"]["H_WR_ZERO"]["samples"], (0.0,) * len(paths))
        self.assertEqual(readout["anytime_td"]["H_WR_ZERO"]["probability"], 0.0)

    def test_personnel_team_collision_fails_closed(self):
        shared = "DUPLICATE_PLAYER"
        home_personnel = TeamPersonnelProfile(
            quarterback_id="H_QB",
            rush_shares=((shared, 1.0),),
            target_shares=(("H_WR", 1.0),),
        )
        away_personnel = TeamPersonnelProfile(
            quarterback_id="A_QB",
            rush_shares=((shared, 1.0),),
            target_shares=(("A_WR", 1.0),),
        )
        paths = EngineADrivePlaySimulator(
            game_id="NFL_COLLISION", home_team="HOME", away_team="AWAY",
            home_profile=TeamDriveProfile(), away_profile=TeamDriveProfile(), seed=800,
        ).simulate(2)
        engine = EngineBParticipationSimulator(
            home_team="HOME", away_team="AWAY",
            home_personnel=home_personnel, away_personnel=away_personnel, seed=801,
        )
        overlays = [engine.assign(path) for path in paths]
        with self.assertRaisesRegex(ValueError, "PLAYER_ID_TEAM_COLLISION"):
            derive_player_market_readouts(
                paths, overlays,
                home_personnel=home_personnel,
                away_personnel=away_personnel,
            )

    def test_player_samples_reconcile_to_engine_a_team_volume_per_simulation(self):
        paths, _, readout = self._readout(30)
        player_ids = set(readout["passing_yards"])
        for index, path in enumerate(paths):
            team_pass_yards = sum(
                play.yards for play in path.plays
                if play.possession == "HOME" and play.play_type == "PASS" and play.pass_complete is True
            )
            home_player_pass = sum(
                readout["passing_yards"][player]["samples"][index]
                for player in player_ids if player.startswith("H_")
            )
            self.assertEqual(home_player_pass, team_pass_yards)

    def test_threshold_pricing_is_push_aware(self):
        _, _, readout = self._readout(
            40,
            lines={
                "passing_yards": {"H_QB": 200.5},
                "receptions": {"H_WR1": 4.0},
            },
        )
        qb = readout["passing_yards"]["H_QB"]["price"]
        self.assertAlmostEqual(qb["over"] + qb["under"] + qb["push"], 1.0)
        wr = readout["receptions"]["H_WR1"]["price"]
        self.assertAlmostEqual(wr["over"] + wr["under"] + wr["push"], 1.0)
        self.assertGreaterEqual(wr["push"], 0.0)

    def test_first_td_probabilities_use_ordered_engine_a_path(self):
        paths, _, readout = self._readout(80)
        total_first_td = sum(row["probability"] for row in readout["first_td"].values())
        no_td = sum(not any(play.points == 7 for play in path.plays) for path in paths) / len(paths)
        self.assertAlmostEqual(total_first_td + no_td, 1.0)

    def test_path_overlay_count_mismatch_fails_closed(self):
        paths, overlays, home_personnel, away_personnel = self._ensemble(4)
        with self.assertRaisesRegex(ValueError, "PARTICIPATION_ENSEMBLE_COUNT_MISMATCH"):
            derive_player_market_readouts(
                paths,
                overlays[:-1],
                home_personnel=home_personnel,
                away_personnel=away_personnel,
            )


if __name__ == "__main__":
    unittest.main()
