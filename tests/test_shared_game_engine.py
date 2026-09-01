import unittest

from sportsedge.engine_registry import engine_registry
from sportsedge.generic_market_engine import generic_market_engine_adapter
from sportsedge.shared_game_engine import build_shared_game_engine_session, score_distribution_sha256
from sportsedge.v7_distribution import simulate_game_distribution


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

    def test_one_distribution_is_reused_for_ml_rl_totals(self):
        calls = []

        def counting_simulator(**kwargs):
            calls.append(dict(kwargs))
            return simulate_game_distribution(**kwargs)

        engine = build_shared_game_engine_session(simulator=counting_simulator)
        base = self.base_input()
        outputs = [
            engine({**base, "market": "MONEYLINE", "line": 0.0, "side": "HOME"}),
            engine({**base, "market": "RUN_LINE", "line": -1.5, "side": "HOME"}),
            engine({**base, "market": "TOTALS", "line": 8.5, "side": "OVER"}),
        ]

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["total_line"], 0.0)
        self.assertEqual({row["distribution_sha256"] for row in outputs}, {outputs[0]["distribution_sha256"]})
        self.assertEqual({row["model_input_hash"] for row in outputs}, {outputs[0]["model_input_hash"]})
        self.assertEqual({row["market"] for row in outputs}, {"MONEYLINE", "RUN_LINE", "TOTALS"})
        self.assertEqual(len({row["readout_sha256"] for row in outputs}), 3)
        self.assertNotEqual(outputs[0]["model_input_hash"], outputs[0]["distribution_sha256"])

    def test_line_and_side_are_post_distribution_readout_only(self):
        calls = []

        def counting_simulator(**kwargs):
            calls.append(dict(kwargs))
            return simulate_game_distribution(**kwargs)

        engine = build_shared_game_engine_session(simulator=counting_simulator)
        base = self.base_input()
        over_85 = engine({**base, "market": "TOTALS", "line": 8.5, "side": "OVER"})
        under_95 = engine({**base, "market": "TOTALS", "line": 9.5, "side": "UNDER"})

        # The stochastic build happens once and receives none of the sportsbook
        # proposition identity. The legacy simulator still requires total_line,
        # so the shared engine supplies a neutral constant rather than the book line.
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["total_line"], 0.0)
        for forbidden in ("market", "line", "side", "team_side", "american_odds", "sportsbook_price"):
            self.assertNotIn(forbidden, calls[0])

        # The proposition changes only the downstream readout. Stochastic identity
        # and the frozen score distribution remain byte-identical.
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

        engine = build_shared_game_engine_session(simulator=counting_simulator)
        base = self.base_input()
        first = engine({**base, "market": "MONEYLINE", "line": 0.0, "side": "HOME"})
        second = engine({**base, "feature_source_hash": "source-v2", "market": "MONEYLINE", "line": 0.0, "side": "HOME"})
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(first["model_input_hash"], second["model_input_hash"])
        self.assertNotEqual(first["distribution_sha256"], second["distribution_sha256"])

    def test_stage1_readouts_match_incumbent_probabilities(self):
        shared = build_shared_game_engine_session()
        base = self.base_input()
        cases = (
            {"market": "MONEYLINE", "line": 0.0, "side": "HOME"},
            {"market": "MONEYLINE", "line": 0.0, "side": "AWAY"},
            {"market": "RUN_LINE", "line": -1.5, "side": "HOME"},
            {"market": "RUN_LINE", "line": 1.5, "side": "AWAY"},
            {"market": "TOTALS", "line": 8.0, "side": "OVER"},
            {"market": "TOTALS", "line": 8.0, "side": "UNDER"},
        )
        for case in cases:
            model_input = {**base, **case}
            incumbent = generic_market_engine_adapter(model_input)
            candidate = shared(model_input)
            with self.subTest(case=case):
                self.assertAlmostEqual(candidate["model_p"], incumbent["model_p"], places=15)
                self.assertAlmostEqual(candidate["push_p"], incumbent["push_p"], places=15)
                self.assertEqual(candidate["mc_paths"], incumbent["mc_paths"])
                self.assertEqual(candidate["seed_policy"], incumbent["seed_policy"])
                self.assertEqual(candidate["engine_version"], incumbent["engine_version"])

    def test_registry_binds_all_three_markets_to_same_session(self):
        registry = engine_registry()
        self.assertIs(registry["MONEYLINE"], registry["RUN_LINE"])
        self.assertIs(registry["RUN_LINE"], registry["TOTALS"])
        self.assertIsNot(registry["TOTALS"], registry["NRFI"])


if __name__ == "__main__":
    unittest.main()
