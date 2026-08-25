import inspect
import unittest

from sportsedge.game_distribution_readout import read_game_probability
from sportsedge.v7_distribution import simulate_game_distribution


class SharedGameDistributionReadoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.distribution = simulate_game_distribution(
            away_mean_runs=4.1,
            home_mean_runs=4.6,
            total_line=0.0,
            simulations=2000,
            seed=1701,
        )

    def test_one_distribution_supports_all_stage1_game_readouts(self):
        rows = [
            read_game_probability(self.distribution, market="MONEYLINE", side="HOME"),
            read_game_probability(self.distribution, market="RUN_LINE", line=-1.5, side="HOME"),
            read_game_probability(self.distribution, market="TOTALS", line=8.5, side="OVER"),
        ]
        self.assertEqual({row.distribution_sha256 for row in rows}, {self.distribution.result_sha256})
        self.assertEqual({row.market for row in rows}, {"MONEYLINE", "RUN_LINE", "TOTALS"})

    def test_moneyline_complements_conserve_probability(self):
        home = read_game_probability(self.distribution, market="MONEYLINE", side="HOME")
        away = read_game_probability(self.distribution, market="MONEYLINE", side="AWAY")
        self.assertAlmostEqual(home.probability + away.probability, 1.0, places=12)
        self.assertEqual(home.push_probability, 0.0)
        self.assertEqual(away.push_probability, 0.0)

    def test_run_line_complements_conserve_probability(self):
        home = read_game_probability(self.distribution, market="RUN_LINE", line=-1.5, side="HOME")
        away = read_game_probability(self.distribution, market="RUN_LINE", line=1.5, side="AWAY")
        self.assertAlmostEqual(home.probability + away.probability, 1.0, places=12)
        self.assertEqual(home.push_probability, 0.0)
        self.assertEqual(away.push_probability, 0.0)

    def test_integer_total_preserves_push_mass(self):
        over = read_game_probability(self.distribution, market="TOTALS", line=8.0, side="OVER")
        under = read_game_probability(self.distribution, market="TOTALS", line=8.0, side="UNDER")
        self.assertAlmostEqual(
            over.probability + under.probability + over.push_probability,
            1.0,
            places=12,
        )
        self.assertAlmostEqual(over.push_probability, under.push_probability, places=12)

    def test_readout_api_has_no_price_or_book_inputs(self):
        parameters = set(inspect.signature(read_game_probability).parameters)
        self.assertFalse(
            parameters.intersection({"american_odds", "decimal_odds", "book_key", "implied_probability"})
        )


if __name__ == "__main__":
    unittest.main()
