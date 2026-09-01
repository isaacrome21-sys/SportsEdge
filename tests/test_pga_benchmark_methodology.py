import unittest

from sportsedge.pga.benchmark import benchmark_probability


class PGABenchmarkMethodologyTests(unittest.TestCase):
    def test_outright_requires_complete_nway_field(self):
        prices = {"A": 500, "B": 700, "C": 900}
        with self.assertRaisesRegex(ValueError, "COMPLETE_FIELD_REQUIRED"):
            benchmark_probability(
                market="OUTRIGHT",
                selection="A",
                prices=prices,
                market_complete=False,
            )
        out = benchmark_probability(
            market="OUTRIGHT",
            selection="A",
            prices=prices,
            market_complete=True,
        )
        self.assertEqual(out.methodology, "MULTIPLICATIVE_NWAY_V1")
        self.assertEqual(out.market_shape, "EXHAUSTIVE_N_WAY_MUTUALLY_EXCLUSIVE")
        self.assertEqual(len(out.quote_set_sha256), 64)

    def test_frl_uses_same_nway_family_not_two_way(self):
        out = benchmark_probability(
            market="FIRST_ROUND_LEADER",
            selection="B",
            prices={"A": 800, "B": 1000, "C": 1200},
            market_complete=True,
        )
        self.assertEqual(out.methodology, "MULTIPLICATIVE_NWAY_V1")

    def test_top_k_is_binary_per_player_and_cross_player_normalization_is_rejected(self):
        out = benchmark_probability(
            market="TOP_K",
            selection="YES",
            prices={"YES": 180, "NO": -220},
        )
        self.assertEqual(out.methodology, "MULTIPLICATIVE_2WAY_V1")
        self.assertEqual(out.market_shape, "PER_SELECTION_BINARY_NONEXHAUSTIVE_ACROSS_PLAYERS")
        with self.assertRaisesRegex(ValueError, "EXACTLY_TWO_QUOTES_REQUIRED"):
            benchmark_probability(
                market="TOP_K",
                selection="Player A",
                prices={"Player A": 180, "Player B": 190, "Player C": 220},
            )

    def test_make_cut_requires_paired_yes_no_quotes(self):
        with self.assertRaisesRegex(ValueError, "PAIRED_QUOTES_REQUIRED"):
            benchmark_probability(
                market="MAKE_CUT",
                selection="YES",
                prices={"YES": -150},
            )

    def test_h2h_uses_two_way_benchmark(self):
        out = benchmark_probability(
            market="H2H",
            selection="A",
            prices={"A": -115, "B": -105},
        )
        self.assertEqual(out.methodology, "MULTIPLICATIVE_2WAY_V1")
        self.assertGreater(out.probability, 0.5)


if __name__ == "__main__":
    unittest.main()
