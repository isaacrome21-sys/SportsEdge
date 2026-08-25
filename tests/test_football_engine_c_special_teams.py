import unittest

from sportsedge.core.simulate.drive_play import EngineADrivePlaySimulator, TeamDriveProfile
from sportsedge.core.simulate.special_teams import TeamSpecialTeamsProfile, derive_special_teams_market_readouts


class FootballEngineCSpecialTeamsTests(unittest.TestCase):
    def _paths(self, n=80):
        return EngineADrivePlaySimulator(
            game_id="NFL_C_TEST",
            home_team="HOME",
            away_team="AWAY",
            home_profile=TeamDriveProfile(field_goal_attempt_rate=1.0, field_goal_skill=0.90),
            away_profile=TeamDriveProfile(field_goal_attempt_rate=1.0, field_goal_skill=0.88),
            seed=7301,
        ).simulate(n)

    def test_kicker_markets_are_derived_from_engine_a_scoring_path(self):
        paths = self._paths()
        readout = derive_special_teams_market_readouts(
            paths,
            home=TeamSpecialTeamsProfile("HOME", "H_K", True),
            away=TeamSpecialTeamsProfile("AWAY", "A_K", True),
        )
        for market in ("fg_made", "kicking_points", "xp_made", "longest_fg_made"):
            self.assertIn(market, readout)
        self.assertEqual(len(readout["fg_made"]["H_K"]["samples"]), len(paths))
        self.assertEqual(len(readout["longest_fg_made"]["HOME"]["samples"]), len(paths))

    def test_kicking_points_reconcile_to_bundled_engine_a_score_convention(self):
        paths = self._paths(25)
        readout = derive_special_teams_market_readouts(
            paths,
            home=TeamSpecialTeamsProfile("HOME", "H_K", True),
            away=TeamSpecialTeamsProfile("AWAY", "A_K", True),
        )
        for index, path in enumerate(paths):
            made_fg = sum(
                play.play_type.upper() == "FIELD_GOAL" and play.points == 3 and play.possession == "HOME"
                for play in path.plays
            )
            offensive_tds = sum(
                play.points == 7 and play.play_type.upper() in {"PASS", "RUSH"} and play.possession == "HOME"
                for play in path.plays
            )
            self.assertEqual(readout["fg_made"]["H_K"]["samples"][index], float(made_fg))
            self.assertEqual(readout["xp_made"]["H_K"]["samples"][index], float(offensive_tds))
            self.assertEqual(readout["kicking_points"]["H_K"]["samples"][index], float(3 * made_fg + offensive_tds))

    def test_longest_made_field_goal_uses_only_made_kicks(self):
        paths = self._paths(30)
        readout = derive_special_teams_market_readouts(
            paths,
            home=TeamSpecialTeamsProfile("HOME", "H_K", True),
            away=TeamSpecialTeamsProfile("AWAY", "A_K", True),
        )
        for index, path in enumerate(paths):
            made = [
                play.kick_distance for play in path.plays
                if play.possession == "HOME" and play.play_type.upper() == "FIELD_GOAL"
                and play.points == 3 and play.kick_distance is not None
            ]
            self.assertEqual(readout["longest_fg_made"]["HOME"]["samples"][index], float(max(made, default=0)))

    def test_unresolved_or_inactive_kicker_fails_closed(self):
        paths = self._paths(2)
        with self.assertRaisesRegex(ValueError, "SPECIAL_TEAMS_PARTICIPATION_UNRESOLVED:H_K"):
            derive_special_teams_market_readouts(
                paths,
                home=TeamSpecialTeamsProfile("HOME", "H_K", None),
                away=TeamSpecialTeamsProfile("AWAY", "A_K", True),
            )
        with self.assertRaisesRegex(ValueError, "STARTING_KICKER_INACTIVE:H_K"):
            derive_special_teams_market_readouts(
                paths,
                home=TeamSpecialTeamsProfile("HOME", "H_K", False),
                away=TeamSpecialTeamsProfile("AWAY", "A_K", True),
            )

    def test_threshold_pricing_is_push_aware(self):
        paths = self._paths(20)
        readout = derive_special_teams_market_readouts(
            paths,
            home=TeamSpecialTeamsProfile("HOME", "H_K", True),
            away=TeamSpecialTeamsProfile("AWAY", "A_K", True),
            lines={"fg_made": {"H_K": 1.5}, "kicking_points": {"H_K": 7.0}},
        )
        for market in ("fg_made", "kicking_points"):
            price = readout[market]["H_K"]["price"]
            self.assertAlmostEqual(price["over"] + price["under"] + price["push"], 1.0)

    def test_market_blind_profile_rejects_book_inputs(self):
        with self.assertRaises(TypeError):
            TeamSpecialTeamsProfile("HOME", "H_K", True, sportsbook_price=-110)


if __name__ == "__main__":
    unittest.main()
