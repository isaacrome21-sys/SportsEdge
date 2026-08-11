import unittest
from datetime import timezone

from sportsedge.card_io import CardIOError, normalize_feature_rows, normalize_quotes


class CardIOTests(unittest.TestCase):
    def test_feature_rows_require_list_of_objects(self):
        with self.assertRaises(CardIOError):
            normalize_feature_rows({})
        with self.assertRaises(CardIOError):
            normalize_feature_rows([1])
        rows = normalize_feature_rows([{"market":"HITS"}])
        self.assertEqual(rows[0]["market"], "HITS")

    def test_quote_timestamp_string_becomes_aware_datetime(self):
        rows = normalize_quotes([{
            "game_id":"1", "market":"HITS", "entity_id":"2", "line":.5,
            "side":"OVER", "american_odds":-110, "retrieved_at":"2026-08-10T20:00:00Z", "ttl_seconds":300,
        }])
        self.assertIsNotNone(rows[0]["retrieved_at"].tzinfo)
        self.assertEqual(rows[0]["retrieved_at"].utcoffset().total_seconds(), 0)

    def test_naive_quote_timestamp_rejected(self):
        with self.assertRaises(CardIOError):
            normalize_quotes([{"retrieved_at":"2026-08-10T20:00:00"}])

    def test_missing_quote_timestamp_rejected(self):
        with self.assertRaises(CardIOError):
            normalize_quotes([{}])


if __name__ == "__main__":
    unittest.main()
