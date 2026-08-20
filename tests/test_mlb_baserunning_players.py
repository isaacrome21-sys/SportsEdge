import random
import unittest

from sportsedge.mlb_baserunning import BaserunningProfile, BaserunningConfig
from sportsedge.mlb_pa_simulator import (
    PAProbabilities, Batter, GameConfig, simulate_game, simulate_many, read_player_markets,
)


def out(pid):
    return Batter(pid, PAProbabilities(bip_out=1.0))


class MLBBaserunningPlayerTests(unittest.TestCase):
    def test_stolen_base_requires_and_consumes_real_base_state(self):
        away = (Batter("runner", PAProbabilities(single=1.0)),) + tuple(out(f"a{i}") for i in range(1, 9))
        home = tuple(out(f"h{i}") for i in range(9))
        running = BaserunningConfig((
            BaserunningProfile("runner", attempt_second=1.0, success_second=1.0),
        ))
        path = simulate_game(GameConfig(away=away, home=home, innings=1, away_baserunning=running), random.Random(4))
        self.assertEqual(path.player_stats["runner"].stolen_bases, 1)
        self.assertEqual(path.player_stats["runner"].caught_stealing, 0)
        self.assertEqual(len(path.sb_attempts), 1)
        self.assertTrue(path.sb_attempts[0].base_occupied_before)
        self.assertEqual((path.sb_attempts[0].from_base, path.sb_attempts[0].to_base), (1, 2))

    def test_empty_bases_cannot_create_stolen_base_attempt(self):
        away = tuple(out(f"a{i}") for i in range(9))
        home = tuple(out(f"h{i}") for i in range(9))
        running = BaserunningConfig((
            BaserunningProfile("a0", attempt_second=1.0, success_second=1.0),
        ))
        path = simulate_game(GameConfig(away=away, home=home, innings=1, away_baserunning=running), random.Random(5))
        self.assertEqual(path.sb_attempts, [])

    def test_player_prop_readouts_are_same_path_counts(self):
        away = (Batter("slugger", PAProbabilities(hr=1.0)),) + tuple(out(f"a{i}") for i in range(1, 9))
        home = tuple(out(f"h{i}") for i in range(9))
        paths = simulate_many(GameConfig(away=away, home=home, innings=9), n=10, seed=6)
        props = read_player_markets(paths, "slugger")
        self.assertEqual(props.hits_pmf, {4: 1.0})
        self.assertEqual(props.total_bases_pmf, {16: 1.0})
        self.assertEqual(props.hr_pmf, {4: 1.0})
        self.assertEqual(props.rbi_pmf, {4: 1.0})
        self.assertEqual(props.runs_pmf, {4: 1.0})
        self.assertEqual(props.h_r_rbi_pmf, {12: 1.0})
        self.assertEqual(props.stolen_bases_pmf, {0: 1.0})


if __name__ == "__main__":
    unittest.main()
