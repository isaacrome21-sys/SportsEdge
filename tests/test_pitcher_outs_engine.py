import unittest

from sportsedge.pitcher_outs_engine import (
    ENGINE_VERSION,
    PitcherOutsEngineError,
    price_pitcher_outs,
)


class PitcherOutsEngineTests(unittest.TestCase):
    def _input(self, *, line=15.5, side="OVER", pool=None):
        return {
            "game_id": "1",
            "market": "PITCHER_OUTS",
            "entity_id": "99",
            "line": line,
            "side": side,
            "feature_source_hash": "a" * 64,
            "features": {"workload_pool": pool or [15, 18, 16, 21, 17, 12, 20, 18, 14, 19]},
        }

    def test_half_run_probability_matches_empirical_ecdf(self):
        out = price_pitcher_outs(self._input(line=15.5, side="OVER"))
        self.assertEqual(out.engine_version, ENGINE_VERSION)
        self.assertEqual(out.sample_size, 10)
        self.assertAlmostEqual(out.model_p, 0.7)
        self.assertEqual(out.push_p, 0.0)

    def test_integer_line_retains_push_mass(self):
        out = price_pitcher_outs(self._input(line=18, side="OVER"))
        self.assertAlmostEqual(out.model_p, 0.3)
        self.assertAlmostEqual(out.push_p, 0.2)
        under = price_pitcher_outs(self._input(line=18, side="UNDER"))
        self.assertAlmostEqual(under.model_p, 0.5)
        self.assertAlmostEqual(out.model_p + under.model_p + out.push_p, 1.0)

    def test_physical_support_is_exact(self):
        with self.assertRaisesRegex(PitcherOutsEngineError, "physical support"):
            price_pitcher_outs(self._input(pool=[15, 18, 16, 21, 17, 28]))
        out = price_pitcher_outs(self._input(line=26.5, side="OVER", pool=[27, 27, 24, 21, 18]))
        self.assertAlmostEqual(out.model_p, 0.4)

    def test_requires_minimum_prior_starts(self):
        with self.assertRaisesRegex(PitcherOutsEngineError, "at least 5"):
            price_pitcher_outs(self._input(pool=[15, 16, 17, 18]))

    def test_quote_side_does_not_change_model_identity(self):
        over = price_pitcher_outs(self._input(line=15.5, side="OVER"))
        under = price_pitcher_outs(self._input(line=18.5, side="UNDER"))
        self.assertEqual(over.model_input_hash, under.model_input_hash)


if __name__ == "__main__":
    unittest.main()
