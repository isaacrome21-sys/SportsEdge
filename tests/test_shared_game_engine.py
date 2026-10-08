import unittest

from sportsedge.engine_registry import engine_registry
from sportsedge.generic_market_engine import generic_market_engine_adapter
from sportsedge.shared_game_engine import (
    SharedGameEngineError,
    V8_PRIMARY_DISTRIBUTION_VERSION,
    V8_PRIMARY_FULL_GAME_DISPERSION_R,
    V8_PRIMARY_GAME_MIN_SIMULATIONS,
    V8_PRIMARY_TEAM_DISPERSION_R,
    build_shared_game_engine_session,
    score_distribution_sha256,
)
from sportsedge.v7_distribution import (
    FULL_GAME_MODE_INDEPENDENT_NB,
    V8_INDEPENDENT_EXTRA_HALF_INNING_MEAN,
    calibrated_full_game_means,
    simulate_game_distribution,
)


class SharedGameEngineStage1Tests(unittest.TestCase):
    def test_explicit_postseason_is_blocked_before_simulation(self):
        def unexpected_simulator(**kwargs):
            self.fail("legacy postseason scoring must not be simulated")

        engine = build_shared_game_engine_session(
            simulator=unexpected_simulator,
            _minimum_simulations_for_test=1000,
        )
        with self.assertRaisesRegex(SharedGameEngineError, "POSTSEASON_LEGACY_SCORE_ENGINE_UNVALIDATED"):
            engine({
                "game_id": "ALDS_GAME4",
                "market": "MONEYLINE",
                "side": "HOME",
                "line": 0.0,
                "rules_mode": "POSTSEASON",
                "away_mean_runs": 4.1,
                "home_mean_runs": 4.6,
                "simulations": 1000,
            })

    def test_invalid_explicit_rules_mode_fails_closed(self):
        engine = build_shared_game_engine_session()
        with self.assertRaisesRegex(SharedGameEngineError, "MLB_GAME_RULES_MODE_INVALID"):
            engine({"game_id": "invalid", "market": "MONEYLINE", "rules_mode": "UNKNOWN"})

    def base_input(self):
        return {
            "game_id": "777",
            "entity_id": "GAME",
            "away_mean_runs": 4.1,
            "home_mean_runs": 4.6,
            "feature_source_hash": "source-v1",
            "simulations": 2000,
        }

    def test_production_floor_rejects_runtime_downshift(self):
        engine = build_shared_game_engine_session()
        with self.assertRaisesRegex(SharedGameEngineError, str(V8_PRIMARY_GAME_MIN_SIMULATIONS)):
            engine({
                **self.base_input(),
                "simulations": V8_PRIMARY_GAME_MIN_SIMULATIONS - 1,
                "market": "MONEYLINE",
                "line": 0.0,
                "side": "HOME",
            })

    def test_test_floor_override_requires_injected_simulator(self):
        with self.assertRaisesRegex(SharedGameEngineError, "requires injected simulator"):
            build_shared_game_engine_session(_minimum_simulations_for_test=1000)

    def test_one_distribution_is_reused_for_ml_rl_totals(self):
        calls = []

        def counting_simulator(**kwargs):
            calls.append(dict(kwargs))
            return simulate_game_distribution(**kwargs)

        engine = build_shared_game_engine_session(
            simulator=counting_simulator, _minimum_simulations_for_test=1000
        )
        base = self.base_input()
        outputs = [
            engine({**base, "market": "MONEYLINE", "line": 0.0, "side": "HOME"}),
            engine({**base, "market": "RUN_LINE", "line": -1.5, "side": "HOME"}),
            engine({**base, "market": "TOTALS", "line": 8.5, "side": "OVER"}),
            engine({**base, "market": "TEAM_TOTALS", "line": 4.5, "side": "OVER", "team_side": "HOME"}),
        ]

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["total_line"], 0.0)
        self.assertNotIn("full_game_dispersion_r", calls[0])
        self.assertEqual(calls[0]["team_dispersion_r"], V8_PRIMARY_TEAM_DISPERSION_R)
        self.assertEqual(calls[0]["extra_half_inning_mean"], V8_INDEPENDENT_EXTRA_HALF_INNING_MEAN)
        self.assertEqual({row["distribution_sha256"] for row in outputs}, {outputs[0]["distribution_sha256"]})
        self.assertEqual({row["model_input_hash"] for row in outputs}, {outputs[0]["model_input_hash"]})
        self.assertEqual(
            {row["market"] for row in outputs},
            {"MONEYLINE", "RUN_LINE", "TOTALS", "TEAM_TOTALS"},
        )
        self.assertEqual(len({row["readout_sha256"] for row in outputs}), 4)

    def test_line_and_side_are_post_distribution_readout_only(self):
        calls = []

        def counting_simulator(**kwargs):
            calls.append(dict(kwargs))
            return simulate_game_distribution(**kwargs)

        engine = build_shared_game_engine_session(
            simulator=counting_simulator, _minimum_simulations_for_test=1000
        )
        base = self.base_input()
        over_85 = engine({**base, "market": "TOTALS", "line": 8.5, "side": "OVER"})
        under_95 = engine({**base, "market": "TOTALS", "line": 9.5, "side": "UNDER"})

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["total_line"], 0.0)
        for forbidden in ("market", "line", "side", "team_side", "american_odds", "sportsbook_price"):
            self.assertNotIn(forbidden, calls[0])

        self.assertEqual(over_85["distribution_sha256"], under_95["distribution_sha256"])
        self.assertEqual(over_85["model_input_hash"], under_95["model_input_hash"])
        self.assertNotEqual(over_85["readout_sha256"], under_95["readout_sha256"])
        self.assertNotEqual(over_85["model_p"], under_95["model_p"])

    def test_score_distribution_digest_excludes_total_line_readout_semantics(self):
        kwargs = {
            "away_mean_runs": 4.1,
            "home_mean_runs": 4.6,
            "simulations": 2000,
            "build_hash": "a" * 64,
            "shared_game_sigma": 0.0,
            "team_sigma": 0.0,
            "team_dispersion_r": V8_PRIMARY_TEAM_DISPERSION_R,
        }
        neutral = simulate_game_distribution(total_line=0.0, **kwargs)
        market_line = simulate_game_distribution(total_line=8.5, **kwargs)

        self.assertEqual(neutral.joint_score_pmf, market_line.joint_score_pmf)
        self.assertNotEqual(neutral.result_sha256, market_line.result_sha256)
        self.assertEqual(score_distribution_sha256(neutral), score_distribution_sha256(market_line))

    def test_distinct_feature_provenance_forces_new_distribution(self):
        calls = []

        def counting_simulator(**kwargs):
            calls.append(dict(kwargs))
            return simulate_game_distribution(**kwargs)

        engine = build_shared_game_engine_session(
            simulator=counting_simulator, _minimum_simulations_for_test=1000
        )
        base = self.base_input()
        first = engine({**base, "market": "MONEYLINE", "line": 0.0, "side": "HOME"})
        second = engine({**base, "feature_source_hash": "source-v2", "market": "MONEYLINE", "line": 0.0, "side": "HOME"})
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(first["model_input_hash"], second["model_input_hash"])
        self.assertNotEqual(first["distribution_sha256"], second["distribution_sha256"])

    def test_stage1_readouts_match_generic_path_under_promoted_dispersion(self):
        """Shared engine and generic adapter must price Stage-1 markets the same."""

        def test_simulator(**kwargs):
            return simulate_game_distribution(**kwargs)

        shared = build_shared_game_engine_session(
            simulator=test_simulator, _minimum_simulations_for_test=1000
        )
        base = self.base_input()
        cases = (
            {"market": "MONEYLINE", "line": 0.0, "side": "HOME"},
            {"market": "MONEYLINE", "line": 0.0, "side": "AWAY"},
            {"market": "RUN_LINE", "line": -1.5, "side": "HOME"},
            {"market": "RUN_LINE", "line": 1.5, "side": "AWAY"},
            {"market": "TOTALS", "line": 8.0, "side": "OVER"},
            {"market": "TOTALS", "line": 8.0, "side": "UNDER"},
            {"market": "TEAM_TOTALS", "line": 4.5, "side": "OVER", "team_side": "HOME"},
            {"market": "TEAM_TOTALS", "line": 3.5, "side": "UNDER", "team_side": "AWAY"},
        )
        for case in cases:
            model_input = {**base, **case}
            generic = generic_market_engine_adapter(model_input)
            candidate = shared(model_input)
            with self.subTest(case=case):
                self.assertEqual(candidate["full_game_distribution_mode"], FULL_GAME_MODE_INDEPENDENT_NB)
                self.assertEqual(candidate["full_game_dispersion_r"], V8_PRIMARY_TEAM_DISPERSION_R)
                self.assertEqual(generic["full_game_distribution_mode"], FULL_GAME_MODE_INDEPENDENT_NB)
                self.assertEqual(generic["full_game_dispersion_r"], V8_PRIMARY_TEAM_DISPERSION_R)
                self.assertEqual(candidate["engine_version"], V8_PRIMARY_DISTRIBUTION_VERSION)
                self.assertAlmostEqual(candidate["model_p"], generic["model_p"], places=15)
                self.assertAlmostEqual(candidate["push_p"], generic["push_p"], places=15)
                self.assertEqual(candidate["mc_paths"], generic["mc_paths"])
                self.assertEqual(candidate["seed_policy"], generic["seed_policy"])
                self.assertEqual(candidate["engine_version"], generic["engine_version"])

    def test_registry_binds_stage1_markets_to_same_session(self):
        registry = engine_registry()
        self.assertIs(registry["MONEYLINE"], registry["RUN_LINE"])
        self.assertIs(registry["RUN_LINE"], registry["TOTALS"])
        self.assertIs(registry["TOTALS"], registry["TEAM_TOTALS"])
        self.assertIsNot(registry["TOTALS"], registry["NRFI"])

    def test_independent_distribution_matches_2026_game_shape(self):
        """Independent team NB keeps team scores ~uncorrelated and ties realistic."""
        away, home = calibrated_full_game_means(4.4, 4.4)
        self.assertLess(away, home)  # home field
        dist = simulate_game_distribution(
            away_mean_runs=away, home_mean_runs=home, total_line=8.5, simulations=40000,
            seed=7, shared_game_sigma=0.0, team_sigma=0.0,
            team_dispersion_r=V8_PRIMARY_TEAM_DISPERSION_R,
            extra_half_inning_mean=V8_INDEPENDENT_EXTRA_HALF_INNING_MEAN,
        )
        self.assertEqual(dist.full_game_distribution_mode, FULL_GAME_MODE_INDEPENDENT_NB)
        # 2026: extras 6.8-9%, shared-pace model gave ~14.5%.
        self.assertLess(dist.regulation_tie_probability, 0.115)
        self.assertGreater(dist.regulation_tie_probability, 0.07)
        self.assertGreater(dist.home_win_probability, 0.5)
        self.assertLess(dist.home_win_probability, 0.53)
        pmf = {tuple(map(int, k.split(","))): v for k, v in dist.joint_score_pmf.items()}
        ea = sum(a * p for (a, _), p in pmf.items()); eh = sum(h * p for (_, h), p in pmf.items())
        cov = sum((a - ea) * (h - eh) * p for (a, h), p in pmf.items())
        va = sum((a - ea) ** 2 * p for (a, _), p in pmf.items()); vh = sum((h - eh) ** 2 * p for (_, h), p in pmf.items())
        self.assertLess(abs(cov / (va * vh) ** 0.5), 0.1)

    def test_shared_and_independent_modes_are_exclusive(self):
        with self.assertRaises(Exception):
            simulate_game_distribution(
                away_mean_runs=4.0, home_mean_runs=4.0, total_line=8.5, simulations=1000, seed=1,
                shared_game_sigma=0.0, team_sigma=0.0,
                full_game_dispersion_r=V8_PRIMARY_FULL_GAME_DISPERSION_R,
                team_dispersion_r=V8_PRIMARY_TEAM_DISPERSION_R,
            )


if __name__ == "__main__":
    unittest.main()
