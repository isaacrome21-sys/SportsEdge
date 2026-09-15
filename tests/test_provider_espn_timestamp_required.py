from datetime import datetime, timezone
import unittest

from sportsedge.market_provider_contract import ProviderContractError, admit_quote


class ProviderESPNTimestampRequiredTests(unittest.TestCase):
    def test_missing_timestamp_fails_contract(self):
        with self.assertRaisesRegex(ProviderContractError, "SOURCE_TIMESTAMP_MISSING"):
            admit_quote(
                {"quote_provider": "ESPN_SCOREBOARD", "sportsbook": "DraftKings", "market": "TOTALS"},
                now=datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
