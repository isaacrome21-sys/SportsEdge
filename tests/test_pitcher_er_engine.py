import unittest

from sportsedge.pitcher_er_engine import PitcherEREngineError, price_pitcher_er


class PitcherEREngineTests(unittest.TestCase):
    def _input(self, *, line=2.5, side="OVER", pool=None):
        return {
            "game_id": "777",
            "market": "PITCHER_ER",
            "entity_id": "42",
            "line": line,
            "side": side,
            "feature_source_hash": "a" * 64,
            "features": {"earned_runs_pool": pool or [0, 1, 2, 2, 3, 4, 5, 1, 0, 6]},
        }

    def test_half_run_price_matches_empirical_distribution(self):
        out = price_pitcher_er(self._input(line=2.5, side="OVER"))
        self.assertAlmostEqual(out.model_p, 4 / 10)
        self.assertEqual(out.push_p, 0.0)

    def test_integer_line_preserves_push_probability(self):
        out = price_pitcher_er(self._input(line=2.0, side="UNDER"))
        self.assertAlmostEqual(out.model_p, 4 / 10)
        self.assertAlmostEqual(out.push_p, 2 / 10)

    def test_probability_mass_conserves_for_both_sides(self):
        over = price_pitcher_er(self._input(line=3.0, side="OVER"))
        under = price_pitcher_er(self._input(line=3.0, side="UNDER"))
        self.assertAlmostEqual(over.model_p + under.model_p + over.push_p, 1.0)
        self.assertAlmostEqual(over.push_p, under.push_p)

    def test_requires_minimum_prior_starts(self):
        with self.assertRaisesRegex(PitcherEREngineError, "at least 5 prior starts"):
            price_pitcher_er(self._input(pool=[1, 2, 3, 4]))

    def test_rejects_negative_or_fractional_er(self):
        with self.assertRaises(PitcherEREngineError):
            price_pitcher_er(self._input(pool=[0, 1, 2, 3, -1]))
        with self.assertRaises(PitcherEREngineError):
            price_pitcher_er(self._input(pool=[0, 1, 2, 3, 2.5]))

    def test_model_identity_is_quote_invariant(self):
        over = price_pitcher_er(self._input(line=2.5, side="OVER"))
        under = price_pitcher_er(self._input(line=3.5, side="UNDER"))
        self.assertEqual(over.model_input_hash, under.model_input_hash)


if __name__ == "__main__":
    unittest.main()
