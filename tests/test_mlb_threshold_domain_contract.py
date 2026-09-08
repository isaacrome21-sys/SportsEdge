import unittest

from sportsedge.mlb_market_binding import (
    BATTER,
    FULL_GAME,
    INTEGER_PUSHABLE,
    MULTIPLICATIVE_2WAY,
    SETTLE_STAT_LINE,
    THRESHOLD_DOMAIN_NONE,
    TWO_WAY,
    BindingError,
    MarketBinding,
    _ou,
)


class ThresholdDomainContractTests(unittest.TestCase):
    def test_market_binding_requires_explicit_threshold_domain(self):
        with self.assertRaises(TypeError):
            MarketBinding(
                market_id="NEW_TOTAL",
                family="GAME_TOTAL",
                ways=TWO_WAY,
                period=FULL_GAME,
                entity_type=BATTER,
                sides=("OVER", "UNDER"),
                threshold_semantics=INTEGER_PUSHABLE,
                devig_class=MULTIPLICATIVE_2WAY,
                settlement_class=SETTLE_STAT_LINE,
                push_supported=True,
            )

    def test_ou_helper_cannot_inherit_threshold_domain(self):
        with self.assertRaises(TypeError):
            _ou("NEW_PROP", "BATTER_PROP", BATTER)

    def test_contradictory_explicit_threshold_domain_fails_closed(self):
        with self.assertRaisesRegex(BindingError, "THRESHOLD_DOMAIN_SEMANTICS_MISMATCH"):
            MarketBinding(
                market_id="NEW_TOTAL",
                family="GAME_TOTAL",
                ways=TWO_WAY,
                period=FULL_GAME,
                entity_type=BATTER,
                sides=("OVER", "UNDER"),
                threshold_semantics=INTEGER_PUSHABLE,
                threshold_domain=THRESHOLD_DOMAIN_NONE,
                devig_class=MULTIPLICATIVE_2WAY,
                settlement_class=SETTLE_STAT_LINE,
                push_supported=True,
            )


if __name__ == "__main__":
    unittest.main()
