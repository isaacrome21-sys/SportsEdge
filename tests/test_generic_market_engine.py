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
        expected = {"HITS", "TOTAL_BASES", "PITCHER_BB", *GAME_MARKETS, *COUNT_MARKETS, *BINARY_MARKETS}
        self.assertEqual(set(registry), expected)

    def test_home_runs_routes_to_measured_generic_path(self):
        self.assertIs(engine_registry()["HOME_RUNS"], generic_market_engine_adapter)
        out = generic_market_engine_adapter({
            "game_id": "g1", "market": "HOME_RUNS", "entity_id": "b1",
            "line": 0.5, "side": "OVER", "expected_count": 0.32,
        })
        self.assertGreater(out["model_p"], 0.0)
        self.assertLess(out["model_p"], 1.0)

    def test_count_market_produces_probability_without_sportsbook_input(self):
        out = generic_market_engine_adapter({
            "game_id": "g1", "market": "PITCHER_K", "entity_id": "p1",
            "line": 5.5, "side": "OVER", "expected_count": 6.2,
        })
        self.assertGreater(out["model_p"], 0.0)
        self.assertLess(out["model_p"], 1.0)

    def test_batter_k_uses_pa_bounded_binomial(self):
        out = generic_market_engine_adapter({
            "game_id": "g1", "market": "BATTER_K", "entity_id": "b1",
            "line": 0.5, "side": "OVER", "expected_count": 1.0, "projected_pa": 4.4,
        })
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

    def test_known_bad_markets_fail_closed(self):
        cases = [
            {"market": "PITCHER_OUTS", "line": 18.5, "side": "OVER", "expected_count": 19.0},
            {"market": "RBI", "line": 0.5, "side": "OVER", "expected_count": 0.7},
            {"market": "PITCHER_ER", "line": 2.5, "side": "OVER", "expected_count": 2.8},
            {"market": "HITS_RUNS_RBIS", "line": 1.5, "side": "OVER", "expected_count": 1.8},
            {"market": "PITCHER_RECORD_WIN", "line": 0.5, "side": "YES", "event_probability": 0.55},
            {"market": "FIRST_HOME_RUN", "line": 0.5, "side": "YES", "event_probability": 0.12},
        ]
        for row in cases:
            with self.subTest(market=row["market"]):
                with self.assertRaises(Exception):
                    generic_market_engine_adapter({"game_id": "g1", "entity_id": "x", **row})

    def test_f5_markets_fail_closed_until_state_model_exists(self):
        for market in ("F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS"):
            with self.subTest(market=market):
                with self.assertRaisesRegex(Exception, "STATE_MODEL_REBUILD_REQUIRED"):
                    generic_market_engine_adapter({
                        "game_id": "g1", "market": market, "entity_id": "game",
                        "line": 0.0, "side": "HOME", "away_mean_runs": 4.1,
                        "home_mean_runs": 4.6,
                    })

    def test_v7_moneyline_is_identity_bound_and_complementary(self):
        base = {
            "game_id": "g1", "market": "MONEYLINE", "entity_id": "game",
            "line": 0.0, "away_mean_runs": 4.3, "home_mean_runs": 4.3,
            "total_line": 8.5, "simulations": 4000,
        }
        home = generic_market_engine_adapter({**base, "side": "HOME"})
        away = generic_market_engine_adapter({**base, "side": "AWAY"})
        self.assertAlmostEqual(home["model_p"] + away["model_p"], 1.0, places=12)
        self.assertEqual(home["seed_policy"], "identity_sha256_256bit")

    def test_moneyline_equals_home_minus_half_run_on_same_v7_paths(self):
        common = {
            "game_id": "g1", "entity_id": "game", "away_mean_runs": 4.1,
            "home_mean_runs": 4.6, "total_line": 8.5, "simulations": 5000,
        }
        ml = generic_market_engine_adapter({**common, "market": "MONEYLINE", "line": 0.0, "side": "HOME"})
        rl = generic_market_engine_adapter({**common, "market": "RUN_LINE", "line": -0.5, "side": "HOME"})
        self.assertAlmostEqual(ml["model_p"], rl["model_p"], places=12)

    def test_alternate_half_run_line_is_derived_from_joint_distribution(self):
        common = {
            "game_id": "g1", "market": "RUN_LINE", "entity_id": "game",
            "away_mean_runs": 4.1, "home_mean_runs": 4.6, "total_line": 8.5,
            "simulations": 5000,
        }
        home_minus = generic_market_engine_adapter({**common, "line": -2.5, "side": "HOME"})
        away_plus = generic_market_engine_adapter({**common, "line": 2.5, "side": "AWAY"})
        self.assertAlmostEqual(home_minus["model_p"] + away_plus["model_p"], 1.0, places=12)

    def test_integer_game_lines_fail_closed_until_push_aware_ev_exists(self):
        for market, side, line in (("RUN_LINE", "HOME", -1.0), ("TOTALS", "OVER", 9.0)):
            with self.subTest(market=market):
                with self.assertRaisesRegex(Exception, "INTEGER_LINE_REQUIRES_PUSH_AWARE_EV"):
                    generic_market_engine_adapter({
                        "game_id": "g1", "market": market, "entity_id": "game",
                        "line": line, "side": side, "away_mean_runs": 4.3,
                        "home_mean_runs": 4.3, "total_line": 8.5, "simulations": 3000,
                    })

    def test_v7_nrfi_candidate_has_plausible_base_rate(self):
        out = generic_market_engine_adapter({
            "game_id": "g1", "market": "NRFI", "entity_id": "game",
            "line": 0.5, "side": "YES", "away_mean_runs": 4.3,
            "home_mean_runs": 4.3, "total_line": 8.5, "simulations": 10000,
        })
        self.assertGreater(out["model_p"], 0.48)
        self.assertLess(out["model_p"], 0.59)

    def test_v7_extras_candidate_removes_old_under_bias_direction(self):
        out = generic_market_engine_adapter({
            "game_id": "g1", "market": "TOTALS", "entity_id": "game",
            "line": 8.5, "side": "OVER", "away_mean_runs": 4.3,
            "home_mean_runs": 4.3, "simulations": 12000,
        })
        self.assertGreater(out["model_p"], 0.50)
        self.assertLess(out["model_p"], 0.57)

    def test_missing_model_feature_fails_closed(self):
        with self.assertRaises(Exception):
            generic_market_engine_adapter({
                "game_id": "g1", "market": "BATTER_K", "entity_id": "b1",
                "line": 0.5, "side": "OVER",
            })


if __name__ == "__main__":
    unittest.main()
