from datetime import datetime, timezone
import unittest

from sportsedge.market_provider_router import free_first_game_quotes, route_quotes

NOW = datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc)


def espn(book="DraftKings", market="MONEYLINE"):
    return {
        "quote_provider": "ESPN_SCOREBOARD",
        "sportsbook": book,
        "market": market,
        "source_updated_at": datetime(2026, 9, 15, 14, 59, 30, tzinfo=timezone.utc),
    }


def paid():
    return {
        "quote_provider": "THE_ODDS_API",
        "sportsbook": "DraftKings",
        "market": "MONEYLINE",
    }


class MarketProviderRouterTests(unittest.TestCase):
    def test_free_eligible_quote_prevents_paid_call(self):
        calls = []
        out = free_first_game_quotes(
            free_fetch=lambda: [espn()],
            paid_fetch=lambda: calls.append("paid") or [paid()],
            required_book="DraftKings",
            now=NOW,
        )
        self.assertEqual(len(out.quotes), 1)
        self.assertEqual(calls, [])
        self.assertEqual(out.quotes[0]["provider_contract"]["provider"], "ESPN_SCOREBOARD")

    def test_free_wrong_book_fails_then_paid_may_run(self):
        calls = []
        out = free_first_game_quotes(
            free_fetch=lambda: [espn(book="ESPN partner")],
            paid_fetch=lambda: calls.append("paid") or [paid()],
            required_book="DraftKings",
            now=NOW,
        )
        self.assertEqual(calls, ["paid"])
        self.assertEqual(len(out.quotes), 1)
        self.assertEqual(out.quotes[0]["provider_contract"]["provider"], "THE_ODDS_API")
        self.assertTrue(out.rejected)

    def test_free_prop_refuses_without_paid_provider(self):
        out = route_quotes([espn(market="HOME_RUNS")], now=NOW)
        self.assertFalse(out.quotes)
        self.assertEqual(out.rejected[0]["reason"], "SOURCE_DOES_NOT_COVER_MARKET")


if __name__ == "__main__":
    unittest.main()
