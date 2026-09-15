from datetime import datetime, timezone
import unittest

from sportsedge.market_provider_contract import ProviderContractError, admit_quote


class ProviderESPNFallbackBookTests(unittest.TestCase):
    def test_espn_partner_is_not_exact_draftkings(self):
        quote = {
            "quote_provider": "ESPN_SCOREBOARD", "sportsbook": "ESPN partner",
            "market": "RUN_LINE", "source_updated_at": "2026-09-15T14:59:30Z",
        }
        with self.assertRaises(ProviderContractError):
            admit_quote(quote, required_book="DraftKings", now=datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
