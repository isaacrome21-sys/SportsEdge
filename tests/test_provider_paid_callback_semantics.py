from datetime import datetime, timezone
import unittest

from sportsedge.market_provider_router import free_first_game_quotes

NOW = datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc)


class ProviderPaidCallbackSemanticsTests(unittest.TestCase):
    def test_paid_callback_runs_only_after_no_free_admission(self):
        calls = []
        free = [{
            "quote_provider": "ESPN_SCOREBOARD", "sportsbook": "ESPN partner",
            "market": "MONEYLINE", "source_updated_at": "2026-09-15T14:59:30Z",
        }]
        paid = [{
            "quote_provider": "THE_ODDS_API", "sportsbook": "DraftKings",
            "market": "MONEYLINE",
        }]
        out = free_first_game_quotes(
            free_fetch=lambda: free,
            paid_fetch=lambda: calls.append("paid") or paid,
            required_book="DraftKings",
            now=NOW,
        )
        self.assertEqual(calls, ["paid"])
        self.assertEqual(out.quotes[0]["provider_contract"]["provider"], "THE_ODDS_API")
        self.assertEqual(out.rejected[0]["reason"], "SOURCE_BOOK_IDENTITY_MISSING_FOR_EXACT_BOOK_CONTRACT")


if __name__ == "__main__":
    unittest.main()
