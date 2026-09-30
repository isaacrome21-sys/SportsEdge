import unittest

from sportsedge.engine_registry import engine_registry
from sportsedge.shared_game_engine import (
    SharedGameEngineError,
    V8_PRIMARY_GAME_MIN_SIMULATIONS,
    build_shared_game_engine_session,
    score_distribution_sha256,
)
from sportsedge.v7_distribution import (
    DEFAULT_FULL_GAME_DISPERSION_R,
    FULL_GAME_MODE_LEGACY_LOGNORMAL,
    FULL_GAME_MODE_SHARED_GAMMA_POISSON,
    V7DistributionError,
    simulate_game_distribution,
)


class SharedGameEngineStage1Tests(unittest.TestCase):
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
            engine({**self.base_input(), "simulations": V8_PRIMARY_GAME_MIN_SIMULATIONS - 1, "market": "MONEYLINE", "line": 0.0, "side": "HOME"})

    def test_test_floor_override_requires_injected_simulator(self):
        with self.assertRaisesRegex(SharedGameEngineError, "requires injected simulator"):
            build_shared_game_engine_session(_minimum_simulations_for_test=1000)

    def test_one_distribution_is_reused_for_ml_rl_totals(self):
        calls = []
        def counting_simulator(**kwargs):
            calls.append(dict(kwargs))
            return simulate_game_distribution(**kwargs)
        engine = build_shared_game_engine_session(simulator=counting_simulator, _minimum_simulations_for_test=1000)
        base = self.base_input()
        outputs = [
            engine({**base, "market": "MONEYLINE", "line": 0.0, "side": "HOME"}),
            engine({**base, "market": "RUN_LINE", "line": -1.5, "side": "HOME"}),
            engine({**base, "market": "TOTALS", "line": 8.5, "side": "OVER"}),
        ]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["total_line"], 0.0)
        self.assertEqual(calls[0]["shared_game_sigma"], 0.0)
        self.assertEqual(calls[0]["team_sigma"], 0.0)
        self.assertEqual(calls[0]["full_game_dispersion_r"], DEFAULT_FULL_GAME_DISPERSION_R)
        self.assertEqual({row["distribution_sha256"] for row in outputs}, {outputs[0]["distribution_sha256"]})
        self.assertEqual({row["model_input_hash"] for row in outputs}, {outputs[0]["model_input_hash"]})
        self.assertEqual({row["full_game_distribution_mode"] for row in outputs}, {FULL_GAME_MODE_SHARED_GAMMA_POISSON})
        self.assertEqual({row["full_game_dispersion_r"] for row in outputs}, {DEFAULT_FULL_GAME_DISPERSION_R})

    def test_line_and_side_are_post_distribution_readout_only(self):
        calls = []
        def counting_simulator(**kwargs):
            calls.append(dict(kwargs))
            return simulate_game_distribution(**kwargs)
        engine = build_shared_game_engine_session(simulator=counting_simulator, _minimum_simulations_for_test=1000)
        base = self.base_input()
        over_85 = engine({**base, "market": "TOTALS", "line": 8.5, "side": "OVER"})
        under_95 = engine({**base, "market": "TOTALS", "line": 9.5, "side": "UNDER"})
        self.assertEqual(len(calls), 1)
        for forbidden in ("market", "line", "side", "team_side", "american_odds", "sportsbook_price"):
            self.assertNotIn(forbidden, calls[0])
        self.assertEqual(over_85["distribution_sha256"], under_95["distribution_sha256"])
        self.assertEqual(over_85["model_input_hash"], under_95["model_input_hash"])
        self.assertNotEqual(over_85["readout_sha256"], under_95["readout_sha256"])

    def test_score_distribution_digest_excludes_total_line_readout_semantics(self):
        kwargs = {"away_mean_runs": 4.1, "home_mean_runs": 4.6, "simulations": 2000, "build_hash": "a" * 64}
        neutral = simulate_game_distribution(total_line=0.0, **kwargs)
        market_line = simulate_game_distribution(total_line=8.5, **kwargs)
        self.assertEqual(neutral.joint_score_pmf, market_line.joint_score_pmf)
        self.assertNotEqual(neutral.result_sha256, market_line.result_sha256)
        self.assertEqual(score_distribution_sha256(neutral), score_distribution_sha256(market_line))

    def test_low_level_default_remains_legacy_for_replay_reproducibility(self):
        result = simulate_game_distribution(away_mean_runs=4.1, home_mean_runs=4.6, total_line=8.5, simulations=2000, seed=7)
        self.assertEqual(result.full_game_distribution_mode, FULL_GAME_MODE_LEGACY_LOGNORMAL)
        self.assertIsNone(result.full_game_dispersion_r)

    def test_dispersion_cannot_stack_with_legacy_sigmas(self):
        with self.assertRaisesRegex(V7DistributionError, "cannot be stacked"):
            simulate_game_distribution(away_mean_runs=4.1, home_mean_runs=4.6, total_line=8.5, simulations=2000, seed=7, full_game_dispersion_r=DEFAULT_FULL_GAME_DISPERSION_R)

    def test_distinct_feature_provenance_forces_new_distribution(self):
        calls = []
        def counting_simulator(**kwargs):
            calls.append(dict(kwargs))
            return simulate_game_distribution(**kwargs)
        engine = build_shared_game_engine_session(simulator=counting_simulator, _minimum_simulations_for_test=1000)
        base = self.base_input()
        first = engine({**base, "market": "MONEYLINE", "line": 0.0, "side": "HOME"})
        second = engine({**base, "feature_source_hash": "source-v2", "market": "MONEYLINE", "line": 0.0, "side": "HOME"})
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(first["model_input_hash"], second["model_input_hash"])
        self.assertNotEqual(first["distribution_sha256"], second["distribution_sha256"])

    def test_registry_binds_all_three_markets_to_same_session(self):
        registry = engine_registry()
        self.assertIs(registry["MONEYLINE"], registry["RUN_LINE"])
        self.assertIs(registry["RUN_LINE"], registry["TOTALS"])
        self.assertIsNot(registry["TOTALS"], registry["NRFI"])


if __name__ == "__main__":
    unittest.main()
