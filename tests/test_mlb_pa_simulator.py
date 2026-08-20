import random
import unittest

from sportsedge.mlb_pa_simulator import (
    PAProbabilities,
    Batter,
    GameConfig,
    simulate_game,
    simulate_many,
    read_game_markets,
    validate_path_conservation,
)


def out_batter(pid):
    return Batter(pid, PAProbabilities(bip_out=1.0))


def hr_batter(pid):
    return Batter(pid, PAProbabilities(hr=1.0))


class MLBPASimulatorTests(unittest.TestCase):
    def test_all_outs_is_zero_zero_and_nrfi(self):
        away = tuple(out_batter(f"a{i}") for i in range(9))
        home = tuple(out_batter(f"h{i}") for i in range(9))
        path = simulate_game(GameConfig(away=away, home=home, innings=9), random.Random(1))
        self.assertEqual((path.away_runs, path.home_runs), (0, 0))
        self.assertEqual(path.first_five_runs, (0, 0))
        self.assertTrue(path.nrfi)
        validate_path_conservation(path)

    def test_one_homer_batter_every_nine_slots_has_known_score(self):
        away = (hr_batter("slugger"),) + tuple(out_batter(f"a{i}") for i in range(1, 9))
        home = tuple(out_batter(f"h{i}") for i in range(9))
        path = simulate_game(GameConfig(away=away, home=home, innings=9), random.Random(2))
        # With a continuous batting order and three outs per inning, the leadoff
        # hitter bats in innings 1, 3, 6 and 9 in this deterministic toy path.
        self.assertEqual(path.away_runs, 4)
        self.assertEqual(path.home_runs, 0)
        self.assertEqual(path.player_stats["slugger"].hr, 4)
        self.assertEqual(path.player_stats["slugger"].hits, 4)
        self.assertEqual(path.player_stats["slugger"].total_bases, 16)
        validate_path_conservation(path)

    def test_readouts_come_from_same_paths(self):
        away = (hr_batter("slugger"),) + tuple(out_batter(f"a{i}") for i in range(1, 9))
        home = tuple(out_batter(f"h{i}") for i in range(9))
        sim = simulate_many(GameConfig(away=away, home=home, innings=9), n=20, seed=7)
        markets = read_game_markets(sim)
        self.assertEqual(markets.home_moneyline_probability, 0.0)
        self.assertEqual(markets.away_moneyline_probability, 1.0)
        self.assertEqual(markets.margin_pmf, {-4: 1.0})
        self.assertEqual(markets.total_pmf, {4: 1.0})
        self.assertEqual(markets.away_team_total_pmf, {4: 1.0})
        self.assertEqual(markets.home_team_total_pmf, {0: 1.0})
        self.assertEqual(markets.nrfi_probability, 0.0)
        self.assertEqual(markets.yrfi_probability, 1.0)
        self.assertAlmostEqual(sum(markets.margin_pmf.values()), 1.0)

    def test_probability_vector_must_sum_to_one(self):
        with self.assertRaises(ValueError):
            PAProbabilities(k=0.5, bip_out=0.4)


if __name__ == "__main__":
    unittest.main()
