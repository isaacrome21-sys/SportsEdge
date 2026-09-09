import unittest
from decimal import Decimal

from sportsedge.devig import (
    DevigError,
    devig_with_policy,
    multiplicative_devig,
    power_devig,
    shin_devig,
)
from sportsedge.edge_floors import FrozenDevigPolicy


def quote(side, odds, *, line=8.5, book="draftkings"):
    return {
        "game_id": "777",
        "period": "FG",
        "market": "TOTALS",
        "entity_id": "777",
        "line": line,
        "side": side,
        "american_odds": odds,
        "book_key": book,
        "is_alternate": False,
    }


def policy():
    return FrozenDevigPolicy(
        policy_id="EDGE_FLOOR_DEVIG_V1",
        longshot_trigger_american_odds=400,
        longshot_trigger_rule="EITHER_SIDE_AT_OR_ABOVE_POSITIVE_400",
        sensitivity_methods=("MULTIPLICATIVE_V1", "POWER_V1", "SHIN_V1"),
        sensitivity_limit_absolute_probability_points=Decimal("0.01"),
        stable_candidate_estimator="MULTIPLICATIVE_V1",
        longshot_candidate_estimator="POWER_V1",
        haircut_probability_points=Decimal("0.0"),
        aggregation_rule="ESTIMATOR_ONLY_NO_MINIMUM_ACROSS_METHODS",
        sensitivity_failure="BLOCK",
    )


class DevigTests(unittest.TestCase):
    def test_multiplicative_devig_matches_hand_calculated_values(self):
        over = quote("OVER", -113)
        under = quote("UNDER", 104)
        d = multiplicative_devig(over, under)

        q_over = 113 / 213
        q_under = 100 / 204
        expected_over = q_over / (q_over + q_under)
        expected_under = q_under / (q_over + q_under)

        self.assertAlmostEqual(d.candidate_raw_implied, q_over, places=12)
        self.assertAlmostEqual(d.opposite_raw_implied, q_under, places=12)
        self.assertAlmostEqual(d.candidate_fair_probability, expected_over, places=12)
        self.assertAlmostEqual(d.opposite_fair_probability, expected_under, places=12)
        self.assertAlmostEqual(d.candidate_fair_probability + d.opposite_fair_probability, 1.0, places=12)
        self.assertAlmostEqual(d.overround, q_over + q_under - 1.0, places=12)
        self.assertLess(d.candidate_fair_probability, d.candidate_raw_implied)

    def test_power_and_shin_are_normalized_two_way_estimators(self):
        longshot = quote("OVER", 400)
        favorite = quote("UNDER", -450)
        for fn, method in ((power_devig, "POWER_V1"), (shin_devig, "SHIN_V1")):
            with self.subTest(method=method):
                d = fn(longshot, favorite)
                self.assertEqual(d.method, method)
                self.assertGreater(d.candidate_fair_probability, 0.0)
                self.assertLess(d.candidate_fair_probability, 1.0)
                self.assertAlmostEqual(
                    d.candidate_fair_probability + d.opposite_fair_probability, 1.0, places=12
                )

    def test_stable_candidate_uses_frozen_multiplicative_estimator(self):
        priced = devig_with_policy(quote("OVER", 150), quote("UNDER", -175), policy=policy())
        self.assertFalse(priced.longshot_triggered)
        self.assertEqual(priced.selected.method, "MULTIPLICATIVE_V1")
        self.assertEqual(priced.sensitivity_spread_probability_points, 0.0)

    def test_plus_400_on_either_side_triggers_longshot_sensitivity(self):
        priced = devig_with_policy(quote("OVER", 400), quote("UNDER", -450), policy=policy())
        self.assertTrue(priced.longshot_triggered)
        self.assertEqual(priced.selected.method, "POWER_V1")
        self.assertEqual(
            tuple(row.method for row in priced.sensitivity_results),
            ("MULTIPLICATIVE_V1", "POWER_V1", "SHIN_V1"),
        )
        self.assertLessEqual(priced.sensitivity_spread_probability_points, 0.01)
        self.assertAlmostEqual(
            priced.fair_probability_for_decision,
            priced.selected.candidate_fair_probability,
            places=15,
        )

    def test_longshot_sensitivity_over_one_pp_blocks_with_specific_reason(self):
        with self.assertRaisesRegex(DevigError, "^LONGSHOT_DEVIG_SENSITIVITY_EXCEEDS_LIMIT:"):
            devig_with_policy(quote("OVER", 400), quote("UNDER", -550), policy=policy())

    def test_pair_requires_same_market_identity(self):
        with self.assertRaisesRegex(DevigError, "identity mismatch"):
            multiplicative_devig(quote("OVER", -110), quote("UNDER", -110, book="fanduel"))

    def test_pair_requires_complementary_sides(self):
        with self.assertRaisesRegex(DevigError, "not complementary"):
            multiplicative_devig(quote("OVER", -110), quote("OVER", -110))


if __name__ == "__main__":
    unittest.main()
