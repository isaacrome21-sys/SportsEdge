from datetime import datetime, timezone
import unittest

from sportsedge.market_provider_contract import ProviderContractError, admit_quote

NOW = datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc)


class MarketProviderContractTests(unittest.TestCase):
    def espn(self, **overrides):
        row = {
            "quote_provider": "ESPN_SCOREBOARD",
            "sportsbook": "DraftKings",
            "market": "MONEYLINE",
            "source_updated_at": datetime(2026, 9, 15, 14, 59, 30, tzinfo=timezone.utc),
        }
        row.update(overrides)
        return row

    def test_espn_payload_draftkings_can_satisfy_exact_book(self):
        admitted = admit_quote(self.espn(), required_book="draftkings", now=NOW)
        self.assertTrue(admitted.exact_book_satisfied)
        self.assertEqual(admitted.provider, "ESPN_SCOREBOARD")
        self.assertEqual(admitted.ttl_seconds, 60)

    def test_espn_partner_cannot_inherit_draftkings_identity(self):
        with self.assertRaisesRegex(ProviderContractError, "SOURCE_BOOK_IDENTITY_MISSING"):
            admit_quote(self.espn(sportsbook="ESPN partner"), required_book="DraftKings", now=NOW)

    def test_espn_prop_is_not_synthesized(self):
        with self.assertRaisesRegex(ProviderContractError, "SOURCE_DOES_NOT_COVER_MARKET"):
            admit_quote(self.espn(market="HOME_RUNS"), now=NOW)

    def test_espn_stale_source_timestamp_fails(self):
        with self.assertRaisesRegex(ProviderContractError, "SOURCE_TIMESTAMP_STALE"):
            admit_quote(
                self.espn(source_updated_at=datetime(2026, 9, 15, 14, 58, 0, tzinfo=timezone.utc)),
                now=NOW,
            )

    def test_unknown_provider_fails_closed(self):
        with self.assertRaisesRegex(ProviderContractError, "SOURCE_PROVIDER_UNREGISTERED"):
            admit_quote({"quote_provider": "MYSTERY", "market": "TOTALS"}, now=NOW)


if __name__ == "__main__":
    unittest.main()
