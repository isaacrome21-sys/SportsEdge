from datetime import datetime, timezone
import unittest

from sportsedge.market_provider_contract import ProviderContractError, admit_quote

NOW = datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc)


class NoSilentProviderSatisfactionTests(unittest.TestCase):
    def test_primary_book_name_cannot_be_inherited_by_fallback(self):
        fallback = {
            "quote_provider": "ESPN_SCOREBOARD",
            "sportsbook": "ESPN partner",
            "market": "TOTALS",
            "source_updated_at": "2026-09-15T14:59:30Z",
            # Even if upstream routing wanted DraftKings, this row itself does not say it.
            "failed_primary_book": "DraftKings",
        }
        with self.assertRaisesRegex(ProviderContractError, "SOURCE_BOOK_IDENTITY_MISSING"):
            admit_quote(fallback, required_book="DraftKings", now=NOW)


if __name__ == "__main__":
    unittest.main()
