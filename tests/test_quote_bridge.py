import unittest

from sportsedge.quote_bridge import QuoteBridgeError, normalize_offer, normalize_offer_snapshot


def offer():
    return {
        "game_id": "777", "market": "hits", "entity_id": "100",
        "line": .5, "side": "over", "american_odds": -125,
        "retrieved_at": "2026-08-10T20:00:00Z", "sportsbook": "DK",
    }


class QuoteBridgeTests(unittest.TestCase):
    def test_normalizes_case_timestamp_and_default_ttl(self):
        q = normalize_offer(offer())
        self.assertEqual(q["market"], "HITS")
        self.assertEqual(q["side"], "OVER")
        self.assertEqual(q["american_odds"], -125)
        self.assertEqual(q["ttl_seconds"], 300)
        self.assertIsNotNone(q["retrieved_at"].tzinfo)

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


if __name__ == "__main__":
    unittest.main()
