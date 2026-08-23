import unittest

from sportsedge.engine_registry import engine_registry
from sportsedge.generic_market_engine import (
    BINARY_MARKETS,
    COUNT_MARKETS,
    GAME_MARKETS,
    PA_BOUNDED_ENGINE_VERSION,
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

    def test_batter_k_uses_pa_bounded_binomial(self):
        out = generic_market_engine_adapter({
            "game_id": "g1",
            "market": "BATTER_K",
            "entity_id": "b1",
            "line": 0.5,
            "side": "OVER",
            "expected_count": 1.0,
            "projected_pa": 4.4,
        })
        # n=floor(4.4+0.5)=4, p=.25, P(X>0)=1-.75^4
        self.assertAlmostEqual(out["model_p"], 1.0 - (0.75 ** 4), places=12)
        self.assertEqual(out["engine_version"], PA_BOUNDED_ENGINE_VERSION)

    def test_pa_round_half_up_policy_is_part_of_probability(self):
        a = generic_market_engine_adapter({
            "game_id": "g1", "market": "BATTER_BB", "entity_id": "b1",
            "line": 0.5, "side": "OVER", "expected_count": 0.8, "projected_pa": 4.49,
        })
        b = generic_market_engine_adapter({
            "game_id": "g1", "market": "BATTER_BB", "entity_id": "b1",
            "line": 0.5, "side": "OVER", "expected_count": 0.8, "projected_pa": 4.50,
        })
        self.assertNotEqual(a["model_p"], b["model_p"])
        self.assertNotEqual(a["model_input_hash"], b["model_input_hash"])

    def test_pa_bounded_market_requires_projected_pa(self):
        with self.assertRaises(Exception):
            generic_market_engine_adapter({
                "game_id": "g1", "market": "SINGLES", "entity_id": "b1",
                "line": 0.5, "side": "OVER", "expected_count": 0.9,
            })

    def test_pa_bounded_market_rejects_implied_p_above_one(self):
        with self.assertRaisesRegex(Exception, "p > 1"):
            generic_market_engine_adapter({
                "game_id": "g1", "market": "BATTER_K", "entity_id": "b1",
                "line": 0.5, "side": "OVER", "expected_count": 5.0, "projected_pa": 4.0,
            })

    def test_pa_bounded_support_is_exact(self):
        out = generic_market_engine_adapter({
            "game_id": "g1", "market": "DOUBLES", "entity_id": "b1",
            "line": 4.5, "side": "OVER", "expected_count": 0.8, "projected_pa": 4.0,
        })
        self.assertEqual(out["model_p"], 0.0)

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
