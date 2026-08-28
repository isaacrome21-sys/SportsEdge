import unittest

from sportsedge.pga.market_pricing import (
    american_to_implied,
    full_field_no_vig,
    full_kelly_fraction,
    price_dead_heat_position,
    price_selection,
    two_way_no_vig,
)
from sportsedge.truth_gate import TruthGateError


class PGAMarketPricingTests(unittest.TestCase):
    def test_canonical_american_odds_validation(self):
        self.assertAlmostEqual(american_to_implied(200), 1 / 3)
        with self.assertRaises(TruthGateError):
            american_to_implied(50)
        with self.assertRaises(TruthGateError):
            american_to_implied(True)

    def test_two_way_devig_normalizes(self):
        a, b = two_way_no_vig(-115, -105)
        self.assertAlmostEqual(a + b, 1.0)
        self.assertGreater(a, b)

    def test_full_field_devig_refuses_partial_field(self):
        prices = {"A": 500, "B": 700, "C": 900}
        with self.assertRaisesRegex(ValueError, "COMPLETE_FIELD_REQUIRED"):
            full_field_no_vig(prices, market_complete=False)
        fair = full_field_no_vig(prices, market_complete=True)
        self.assertAlmostEqual(sum(fair.values()), 1.0)

    def test_full_kelly_is_bankroll_bounded(self):
        self.assertGreaterEqual(full_kelly_fraction(0.8, 200), 0.0)
        self.assertLessEqual(full_kelly_fraction(0.8, 200), 1.0)

    def test_standard_market_price_has_edge_ev_and_fair_odds(self):
        out = price_selection(
            market="OUTRIGHT",
            selection="Player A",
            offered_american=500,
            model_probability=0.20,
            market_probability=0.16,
        )
        self.assertAlmostEqual(out.edge, 0.04)
        self.assertGreater(out.expected_value, 0.0)
        self.assertGreaterEqual(out.full_kelly, 0.0)
        self.assertLessEqual(out.full_kelly, 1.0)

    def test_dead_heat_position_prices_expected_paid_fraction_not_raw_hit_rate(self):
        out = price_dead_heat_position(
            market="TOP_5",
            selection="Player A",
            offered_american=400,
            raw_finish_probability=0.30,
            expected_paid_fraction=0.25,
        )
        self.assertAlmostEqual(out.expected_value, 0.25)
        with self.assertRaisesRegex(ValueError, "EXCEEDS_HIT_PROBABILITY"):
            price_dead_heat_position(
                market="TOP_5",
                selection="Player A",
                offered_american=400,
                raw_finish_probability=0.20,
                expected_paid_fraction=0.25,
            )


if __name__ == "__main__":
    unittest.main()
