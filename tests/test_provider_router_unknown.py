from datetime import datetime, timezone
import unittest

from sportsedge.market_provider_router import route_quotes


class ProviderRouterUnknownTests(unittest.TestCase):
    def test_unknown_provider_is_rejected_not_passed_through(self):
        out = route_quotes([{"quote_provider": "UNKNOWN", "market": "MONEYLINE"}], now=datetime(2026, 9, 15, tzinfo=timezone.utc))
        self.assertFalse(out.quotes)
        self.assertEqual(out.rejected[0]["reason"], "SOURCE_PROVIDER_UNREGISTERED")


if __name__ == "__main__":
    unittest.main()
