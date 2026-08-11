import unittest

from sportsedge.card_io import CardIOError, normalize_feature_rows, normalize_quotes


def quote():
    return {"game_id":"1","period":"FG","market":"HITS","entity_id":"2","line":.5,"side":"OVER","book_key":"draftkings","is_alternate":False,"raw_market_name":"Player Hits","american_odds":-110,"retrieved_at":"2026-08-10T20:00:00Z","ttl_seconds":300}


class CardIOTests(unittest.TestCase):
    def test_feature_rows_require_list_of_objects(self):
        with self.assertRaises(CardIOError): normalize_feature_rows({})
        with self.assertRaises(CardIOError): normalize_feature_rows([1])
        rows=normalize_feature_rows([{"market":"HITS"}]); self.assertEqual(rows[0]["market"],"HITS")

    def test_quote_timestamp_string_becomes_aware_datetime(self):
        rows=normalize_quotes([quote()])
        self.assertIsNotNone(rows[0]["retrieved_at"].tzinfo)
        self.assertEqual(rows[0]["retrieved_at"].utcoffset().total_seconds(),0)

    def test_naive_quote_timestamp_rejected(self):
        q=quote(); q["retrieved_at"]="2026-08-10T20:00:00"
        with self.assertRaises(CardIOError): normalize_quotes([q])

    def test_missing_taxonomy_rejected(self):
        q=quote(); del q["book_key"]
        with self.assertRaisesRegex(CardIOError,"QUOTE_IDENTITY_INCOMPLETE"): normalize_quotes([q])

    def test_missing_quote_timestamp_rejected(self):
        q=quote(); del q["retrieved_at"]
        with self.assertRaises(CardIOError): normalize_quotes([q])


if __name__ == "__main__": unittest.main()
