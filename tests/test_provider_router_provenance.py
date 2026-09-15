from datetime import datetime, timezone
import unittest

from sportsedge.market_provider_router import route_quotes


class ProviderRouterProvenanceTests(unittest.TestCase):
    def test_admitted_quote_carries_provider_contract(self):
        out = route_quotes([{
            "quote_provider": "ESPN_SCOREBOARD", "sportsbook": "DraftKings", "market": "MONEYLINE",
            "source_updated_at": "2026-09-15T14:59:30Z",
        }], now=datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc))
        meta = out.quotes[0]["provider_contract"]
        self.assertEqual(meta["provider"], "ESPN_SCOREBOARD")
        self.assertEqual(meta["sportsbook"], "DraftKings")
        self.assertEqual(meta["ttl_seconds"], 60)


if __name__ == "__main__":
    unittest.main()
