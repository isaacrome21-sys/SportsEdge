import unittest

from sportsedge.quote_bridge import QuoteBridgeError, normalize_offer, normalize_offer_snapshot


def offer():
    return {
        "game_id": "777", "period": "FG", "market": "hits", "entity_id": "100",
        "line": .5, "side": "over", "american_odds": -125,
        "book_key": "draftkings", "is_alternate": False,
        "raw_market_name": "Player Hits",
        "retrieved_at": "2026-08-10T20:00:00Z", "sportsbook": "DK",
    }


class QuoteBridgeTests(unittest.TestCase):
    def test_normalizes_full_canonical_identity_and_default_ttl(self):
        q = normalize_offer(offer())
        self.assertEqual(q["market"], "HITS")
        self.assertEqual(q["period"], "FG")
        self.assertEqual(q["side"], "OVER")
        self.assertEqual(q["book_key"], "draftkings")
        self.assertFalse(q["is_alternate"])
        self.assertEqual(q["raw_market_name"], "Player Hits")
        self.assertEqual(q["american_odds"], -125)
        self.assertEqual(q["ttl_seconds"], 300)
        self.assertIsNotNone(q["retrieved_at"].tzinfo)

    def test_missing_required_identity_field_fails_closed(self):
        for field in ("period", "book_key", "is_alternate", "raw_market_name"):
            o = offer(); del o[field]
            with self.subTest(field=field), self.assertRaisesRegex(QuoteBridgeError, "QUOTE_IDENTITY_INCOMPLETE"):
                normalize_offer(o)

    def test_blank_required_identity_field_fails_closed(self):
        o = offer(); o["book_key"] = "  "
        with self.assertRaisesRegex(QuoteBridgeError, "QUOTE_IDENTITY_INCOMPLETE"):
            normalize_offer(o)

    def test_is_alternate_must_be_boolean(self):
        o = offer(); o["is_alternate"] = 0
        with self.assertRaisesRegex(QuoteBridgeError, "QUOTE_IDENTITY_INCOMPLETE"):
            normalize_offer(o)

    def test_unsupported_period_fails_closed(self):
        o = offer(); o["period"] = "UNKNOWN"
        with self.assertRaises(QuoteBridgeError):
            normalize_offer(o)

    def test_invalid_odds_fail_closed(self):
        o = offer(); o["american_odds"] = -95
        with self.assertRaises(QuoteBridgeError):
            normalize_offer(o)

    def test_naive_timestamp_fails_closed(self):
        o = offer(); o["retrieved_at"] = "2026-08-10T20:00:00"
        with self.assertRaises(QuoteBridgeError):
            normalize_offer(o)

    def test_snapshot_preserves_bad_rows_as_failures(self):
        bad = offer(); bad["market"] = "RBI"
        quotes, failures = normalize_offer_snapshot([offer(), bad])
        self.assertEqual(len(quotes), 1)
        self.assertEqual(len(failures), 1)
        self.assertIn("unsupported market", failures[0]["reason"])

    def test_duplicate_offer_is_explicit_failure(self):
        quotes, failures = normalize_offer_snapshot([offer(), offer()])
        self.assertEqual(len(quotes), 1)
        self.assertEqual(len(failures), 1)
        self.assertIn("duplicate sportsbook offer", failures[0]["reason"])

    def test_same_selection_different_books_are_distinct_quotes(self):
        other = offer(); other["book_key"] = "fanduel"
        quotes, failures = normalize_offer_snapshot([offer(), other])
        self.assertEqual(len(quotes), 2)
        self.assertEqual(failures, [])

    def test_primary_and_alternate_lines_are_distinct_quotes(self):
        alt = offer(); alt["is_alternate"] = True
        quotes, failures = normalize_offer_snapshot([offer(), alt])
        self.assertEqual(len(quotes), 2)
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
