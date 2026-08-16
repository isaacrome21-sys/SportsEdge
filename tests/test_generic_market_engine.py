import unittest

from sportsedge.engine_registry import engine_registry
from sportsedge.generic_market_engine import (
    BINARY_MARKETS,
    COUNT_MARKETS,
    GAME_MARKETS,
    generic_market_engine_adapter,
)


class GenericMarketEngineTests(unittest.TestCase):
    def test_registry_covers_every_expanded_runtime_market(self):
        registry = engine_registry()
        expected = {
            "HITS", "TOTAL_BASES", "PITCHER_BB",
            *GAME_MARKETS, *COUNT_MARKETS, *BINARY_MARKETS,
        }
        self.assertEqual(set(registry), expected)

    def test_count_market_produces_probability_without_sportsbook_input(self):
        out = generic_market_engine_adapter({
            "game_id": "g1",
            "market": "PITCHER_K",
            "entity_id": "p1",
            "line": 5.5,
            "side": "OVER",
            "expected_count": 6.2,
        })
        self.assertGreater(out["model_p"], 0.0)
        self.assertLess(out["model_p"], 1.0)
        self.assertEqual(out["market"], "PITCHER_K")

    def test_binary_market_is_complementary(self):
        yes = generic_market_engine_adapter({
            "game_id": "g1", "market": "PITCHER_RECORD_WIN", "entity_id": "p1",
            "line": 0.5, "side": "YES", "event_probability": 0.61,
        })
        no = generic_market_engine_adapter({
            "game_id": "g1", "market": "PITCHER_RECORD_WIN", "entity_id": "p1",
            "line": 0.5, "side": "NO", "event_probability": 0.61,
        })
        self.assertAlmostEqual(yes["model_p"] + no["model_p"], 1.0, places=12)

    def test_v7_game_market_produces_moneyline_probability(self):
        out = generic_market_engine_adapter({
            "game_id": "g1",
            "market": "MONEYLINE",
            "entity_id": "home",
            "line": 0.0,
            "side": "HOME",
            "away_mean_runs": 4.1,
            "home_mean_runs": 4.6,
            "total_line": 8.5,
            "simulations": 1000,
            "seed": 9,
        })
        self.assertGreater(out["model_p"], 0.0)
        self.assertLess(out["model_p"], 1.0)
        self.assertEqual(out["mc_paths"], 1000)

    def test_missing_model_feature_fails_closed(self):
        with self.assertRaises(Exception):
            generic_market_engine_adapter({
                "game_id": "g1", "market": "RBI", "entity_id": "b1",
                "line": 0.5, "side": "OVER",
            })


if __name__ == "__main__":
    unittest.main()
