import unittest

from sportsedge.sports.nfl.v2k_drive_core import SimulationResult
from sportsedge.sports.nfl.v2k_joint_markets import (
    AUTHORITY,
    V2KJointMarketError,
    derive_v2k_full_game_markets,
    signed_key_mass,
)


def _res(home: int, away: int) -> SimulationResult:
    return SimulationResult(
        home_score=home,
        away_score=away,
        margin=home - away,
        total=home + away,
        team_totals={"H": home, "A": away},
        path=(),
    )


class TestNFLV2KJointMarkets(unittest.TestCase):
    def test_authority_is_zero(self):
        self.assertFalse(any(AUTHORITY.values()))

    def test_markets_and_key_mass_from_one_path_set(self):
        rows = [_res(24, 17), _res(20, 23), _res(31, 24), _res(17, 17)]
        priced = derive_v2k_full_game_markets(
            rows,
            period="FG",
            home_team="H",
            away_team="A",
            spread_line=-3.0,
            total_line=45.5,
            home_team_total_line=23.5,
            away_team_total_line=21.5,
        )
        self.assertEqual(priced["n_paths"], 4)
        ml = priced["moneyline"]
        self.assertAlmostEqual(ml["home_win"] + ml["away_win"] + ml["tie"], 1.0)
        self.assertEqual(priced["signed_key_mass"]["7"], 0.5)
        self.assertIn("home_team_total", priced)

    def test_rejects_non_fg_and_broken_conservation(self):
        with self.assertRaises(V2KJointMarketError):
            derive_v2k_full_game_markets([_res(21, 17)], period="Q1", home_team="H", away_team="A", spread_line=-3, total_line=40)
        broken = SimulationResult(home_score=21, away_score=17, margin=0, total=99, team_totals={"H": 21, "A": 17}, path=())
        with self.assertRaises(V2KJointMarketError):
            derive_v2k_full_game_markets([broken], period="FG", home_team="H", away_team="A", spread_line=-3, total_line=40)

    def test_signed_key_table_keys_are_frozen(self):
        mass = signed_key_mass([3, -3, 7, 14, 0])
        self.assertEqual(set(mass), {"-7", "-3", "3", "7"})
        self.assertEqual(mass["3"], 0.2)
        self.assertEqual(mass["-7"], 0.0)


if __name__ == "__main__":
    unittest.main()
