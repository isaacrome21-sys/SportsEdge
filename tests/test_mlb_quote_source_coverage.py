import unittest

from sportsedge.additional_mlb_odds_source import CANONICAL_MARKETS as ADDITIONAL_MARKETS
from sportsedge.draftkings_prop_source import COUNT_MARKETS
from sportsedge.quote_bridge import SUPPORTED_MARKETS


FEATURED_GAME_MARKETS = frozenset({"MONEYLINE", "RUN_LINE", "TOTALS"})


class MLBQuoteSourceCoverageTests(unittest.TestCase):
    def test_declared_source_capability_covers_entire_canonical_surface(self):
        count = frozenset(COUNT_MARKETS)
        additional = frozenset(ADDITIONAL_MARKETS)
        self.assertFalse(count & FEATURED_GAME_MARKETS)
        self.assertFalse(count & additional)
        self.assertFalse(FEATURED_GAME_MARKETS & additional)

        source_capability = count | FEATURED_GAME_MARKETS | additional
        self.assertEqual(source_capability, set(SUPPORTED_MARKETS))
        self.assertEqual(len(source_capability), 36)

    def test_source_capability_is_not_runtime_or_evidence_promotion(self):
        # This test intentionally locks terminology: a market having a quote-source
        # mapping does not imply that a sportsbook posts it, that a model can price
        # it, or that any validation evidence exists.
        self.assertEqual(len(COUNT_MARKETS), 26)
        self.assertEqual(len(ADDITIONAL_MARKETS), 7)
        self.assertEqual(len(FEATURED_GAME_MARKETS), 3)


if __name__ == "__main__":
    unittest.main()
