from __future__ import annotations

import unittest

from sportsedge.sports.cfb.market_benchmark import (
    CFBMarketBenchmarkError,
    build_historical_market_benchmark,
)


SOURCE_SHA = "a" * 64


def market_rows():
    base = {
        "game_id": "401",
        "season": "2025",
        "game_desc": "Away@Home",
        "date_time": "2025-09-01T12:00:00Z",
        "home_team_id": "1",
        "away_team_id": "2",
        "opening_lines": "",
        "opening_odds": "",
    }
    rows = []
    for book, spread, total, home_ml, away_ml in (
        ("BookA", -3.0, 50.0, -150, 130),
        ("BookB", -4.0, 52.0, -140, 120),
    ):
        rows.extend(
            [
                {**base, "book": book, "market_type": "spread", "abbr": "Home", "lines": str(spread), "odds": ""},
                {**base, "book": book, "market_type": "spread", "abbr": "Away", "lines": str(-spread), "odds": ""},
                {**base, "book": book, "market_type": "total", "abbr": "over", "lines": str(total), "odds": "-110"},
                {**base, "book": book, "market_type": "total", "abbr": "under", "lines": str(total), "odds": "-110"},
                {**base, "book": book, "market_type": "money_line", "abbr": "Home", "lines": "", "odds": str(home_ml)},
                {**base, "book": book, "market_type": "money_line", "abbr": "Away", "lines": "", "odds": str(away_ml)},
            ]
        )
    return rows


class TestCFBMarketBenchmark(unittest.TestCase):
    def test_builds_deterministic_research_only_consensus(self):
        rows = market_rows()
        report = build_historical_market_benchmark(
            rows, source_sha256=SOURCE_SHA, expected_row_count=len(rows)
        )
        self.assertEqual(report["status"], "RESEARCH_ONLY_NOT_PROMOTION_EVIDENCE")
        self.assertEqual(report["row_count"], 12)
        self.assertEqual(report["book_count"], 2)
        self.assertEqual(
            report["reference_game_counts"],
            {"money_line": 1, "spread": 1, "total": 1},
        )
        game = report["game_references"][0]
        self.assertEqual(game["game_id"], "401")
        self.assertAlmostEqual(game["home_spread_consensus"], -3.5)
        self.assertAlmostEqual(game["total_consensus"], 51.0)
        self.assertEqual(game["spread_book_count"], 2)
        self.assertEqual(game["total_book_count"], 2)
        self.assertEqual(game["moneyline_book_count"], 2)
        self.assertTrue(0.0 < game["home_moneyline_novig_consensus"] < 1.0)
        self.assertTrue(report["interpretation"]["market_reference_is_research_context_only"])
        self.assertFalse(report["interpretation"]["market_reference_may_rank_model_candidates"])
        self.assertFalse(report["interpretation"]["row_order_has_temporal_semantics"])
        for value in report["authority"].values():
            self.assertIs(value, False)

        reversed_report = build_historical_market_benchmark(
            reversed(rows), source_sha256=SOURCE_SHA, expected_row_count=len(rows)
        )
        self.assertEqual(report["report_sha256"], reversed_report["report_sha256"])
        self.assertEqual(report["game_references"], reversed_report["game_references"])

    def test_multiple_distinct_values_from_same_book_are_ambiguous_not_ordered(self):
        rows = market_rows()
        extra = dict(rows[0])
        extra["lines"] = "-3.5"
        rows.append(extra)
        report = build_historical_market_benchmark(
            rows, source_sha256=SOURCE_SHA, expected_row_count=len(rows)
        )
        self.assertEqual(report["ambiguous_book_game_groups"]["spread_book_game"], 1)
        game = report["game_references"][0]
        self.assertAlmostEqual(game["home_spread_consensus"], -4.0)
        self.assertEqual(game["spread_book_count"], 1)

    def test_unmatched_team_label_does_not_invent_direction(self):
        rows = market_rows()
        for row in rows:
            if row["market_type"] == "spread":
                row["abbr"] = "UNKNOWN"
        report = build_historical_market_benchmark(
            rows, source_sha256=SOURCE_SHA, expected_row_count=len(rows)
        )
        self.assertEqual(report["reference_game_counts"]["spread"], 0)
        self.assertEqual(report["side_matched_rows_by_market"]["spread"], 0)

    def test_row_count_mismatch_fails_closed(self):
        with self.assertRaisesRegex(CFBMarketBenchmarkError, "ROW_COUNT_MISMATCH"):
            build_historical_market_benchmark(
                market_rows(), source_sha256=SOURCE_SHA, expected_row_count=99
            )

    def test_invalid_source_hash_fails_closed(self):
        with self.assertRaisesRegex(CFBMarketBenchmarkError, "SOURCE_SHA256_INVALID"):
            build_historical_market_benchmark(market_rows(), source_sha256="not-a-hash")

    def test_unknown_market_fails_closed(self):
        rows = market_rows()
        rows[0]["market_type"] = "player_prop"
        with self.assertRaisesRegex(CFBMarketBenchmarkError, "MARKET_INVALID"):
            build_historical_market_benchmark(rows, source_sha256=SOURCE_SHA)


if __name__ == "__main__":
    unittest.main()
