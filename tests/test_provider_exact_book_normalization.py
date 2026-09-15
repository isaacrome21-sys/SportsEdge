from datetime import datetime, timezone
import unittest

from sportsedge.market_provider_contract import admit_quote

NOW = datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc)


class ProviderExactBookNormalizationTests(unittest.TestCase):
    def test_source_owned_book_name_normalizes_case_and_punctuation(self):
        quote = {
            "quote_provider": "ESPN_SCOREBOARD",
            "sportsbook": "DraftKings",
            "market": "MONEYLINE",
            "source_updated_at": "2026-09-15T14:59:30Z",
        }
        out = admit_quote(quote, required_book="draft-kings", now=NOW)
        self.assertTrue(out.exact_book_satisfied)
        self.assertEqual(out.sportsbook, "DraftKings")


if __name__ == "__main__":
    unittest.main()
