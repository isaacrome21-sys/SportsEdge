from datetime import datetime, timezone
import unittest

from sportsedge.market_provider_router import free_first_game_quotes


class ProviderFreeFirstContractTests(unittest.TestCase):
    def test_free_only_mode_is_supported(self):
        now = datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc)
        row = {"quote_provider": "ESPN_SCOREBOARD", "sportsbook": "DraftKings", "market": "TOTALS", "source_updated_at": "2026-09-15T14:59:30Z"}
        out = free_first_game_quotes(free_fetch=lambda: [row], paid_fetch=None, now=now)
        self.assertEqual(len(out.quotes), 1)
        self.assertFalse(out.rejected)


if __name__ == "__main__":
    unittest.main()
