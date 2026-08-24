import unittest

from sportsedge.rbi_engine import RBIEngineError, price_rbi


class RBIEngineTests(unittest.TestCase):
    def _input(self, *, line=0.5, side="OVER", pool=None):
        return {
            "game_id": "777",
            "market": "RBI",
            "entity_id": "101",
            "line": line,
            "side": side,
            "feature_source_hash": "b" * 64,
            "features": {"rbi_pool": pool or [0, 0, 1, 0, 2, 1, 0, 3, 0, 1, 2, 0]},
        }

    def test_half_run_price_matches_empirical_distribution(self):
        out = price_rbi(self._input(line=0.5, side="OVER"))
        self.assertAlmostEqual(out.model_p, 6 / 12)
        self.assertEqual(out.push_p, 0.0)

    def test_adjacent_lines_can_have_different_shape_without_poisson_constraint(self):
        over_05 = price_rbi(self._input(line=0.5, side="OVER"))
        over_15 = price_rbi(self._input(line=1.5, side="OVER"))
        self.assertAlmostEqual(over_05.model_p, 6 / 12)
        self.assertAlmostEqual(over_15.model_p, 3 / 12)
        self.assertGreater(over_05.model_p, over_15.model_p)

    def test_integer_line_preserves_push_probability(self):
        out = price_rbi(self._input(line=1.0, side="UNDER"))
        self.assertAlmostEqual(out.model_p, 6 / 12)
        self.assertAlmostEqual(out.push_p, 3 / 12)

    def test_requires_minimum_prior_games(self):
        with self.assertRaisesRegex(RBIEngineError, "at least 10 prior games"):
            price_rbi(self._input(pool=[0, 1, 0, 2, 0, 1, 0, 0, 1]))

    def test_model_identity_is_quote_invariant(self):
        a = price_rbi(self._input(line=0.5, side="OVER"))
        b = price_rbi(self._input(line=1.5, side="UNDER"))
        self.assertEqual(a.model_input_hash, b.model_input_hash)


if __name__ == "__main__":
    unittest.main()
