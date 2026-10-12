"""Tests for the actionability breakdown (sportsedge.actionability).

Unit-tests the classification rules on synthetic rows and the summary
math; integration through run_full with recorded fixtures lives in
test_uncertainty_bands.py (both annotations land on the same rows).
Recorded fixtures only -- no network.
"""
import unittest

from sportsedge import actionability as A


def priced(status, **extra):
    row = {"sport": "MLB", "market": "PITCHER_K",
           "model_probability": 0.6, "prior_start_count": 12,
           "status": status}
    row.update(extra)
    return row


class ClassifyTest(unittest.TestCase):
    def test_research_candidate_is_actionable(self):
        bucket, detail = A.classify_row(priced(
            "RESEARCH_CANDIDATE_NOT_VALIDATED",
            quote_status="RECENT_CAPTURED_QUOTE"))
        self.assertEqual(bucket, "ACTIONABLE")
        self.assertIn("FRESH_PAIRED_QUOTES", detail)

    def test_research_edge_game_is_actionable_with_caveat(self):
        bucket, detail = A.classify_row({
            "sport": "NFL", "market": "SPREAD", "estimate_p": 0.55,
            "status": "RESEARCH_EDGE"})
        self.assertEqual(bucket, "ACTIONABLE")
        self.assertIn("GAME_QUOTE_FRESHNESS_UNVERIFIED", detail)

    def test_actionable_status_without_probability_is_blocked(self):
        # Fail closed: a phantom candidate must never classify ACTIONABLE.
        bucket, _ = A.classify_row(
            {"status": "RESEARCH_CANDIDATE_NOT_VALIDATED"})
        self.assertEqual(bucket, "BLOCKED")

    def test_stale_quote_is_watch(self):
        bucket, detail = A.classify_row(priced(
            "WATCH_QUOTE_NOT_CURRENT", quote_status="STALE_QUOTE"))
        self.assertEqual(bucket, "WATCH")
        self.assertIn("WATCH_QUOTE_NOT_CURRENT", detail)
        self.assertIn("STALE_QUOTE", detail)

    def test_below_floor_and_price_cap_are_watch(self):
        for status in ("WATCH_BELOW_EV_FLOOR", "WATCH_PRICE_CAP",
                       "WATCH_LINEUP_NOT_CONFIRMED",
                       "WATCH_PLAYER_PARTICIPATION_UNVERIFIED"):
            bucket, _ = A.classify_row(priced(status))
            self.assertEqual(bucket, "WATCH", status)

    def test_game_below_threshold_is_watch(self):
        bucket, _ = A.classify_row({"sport": "NFL", "market": "TOTAL",
                                    "estimate_p": 0.5,
                                    "status": "BELOW_THRESHOLD"})
        self.assertEqual(bucket, "WATCH")

    def test_unpriced_is_blocked(self):
        bucket, detail = A.classify_row(
            {"status": "NO_MODEL_OR_MARKET",
             "reason": "MARKET_NOT_SUPPORTED_BY_REAL_PITCHER_ENGINE"})
        self.assertEqual(bucket, "BLOCKED")
        self.assertIn("NO_MODEL_OR_MARKET", detail)

    def test_prepricing_blocked_is_blocked(self):
        bucket, _ = A.classify_row({
            "status": "BLOCKED_PREPRICING_PITCHER_UNCONFIRMED",
            "reason": "PROBABLE_PITCHER_UNCONFIRMED:Milwaukee Brewers"})
        self.assertEqual(bucket, "BLOCKED")

    def test_invalid_probability_is_blocked(self):
        bucket, _ = A.classify_row(priced("RESEARCH_EDGE",
                                          model_probability=1.5))
        self.assertEqual(bucket, "BLOCKED")


class SummaryTest(unittest.TestCase):
    def rows(self):
        return [
            priced("RESEARCH_CANDIDATE_NOT_VALIDATED",
                   quote_status="RECENT_CAPTURED_QUOTE"),
            {"sport": "NFL", "market": "SPREAD", "estimate_p": 0.55,
             "status": "RESEARCH_EDGE"},
            priced("WATCH_QUOTE_NOT_CURRENT", quote_status="STALE_QUOTE"),
            priced("WATCH_BELOW_EV_FLOOR"),
            {"status": "NO_MODEL_OR_MARKET", "reason": "MARKET_NOT_SUPPORTED"},
            {"status": "BLOCKED_PREPRICING_QB_IDENTITY_UNVERIFIED",
             "reason": "AWAY_QB_IDENTITY_UNVERIFIABLE"},
            {"status": "NO_MODEL_OR_MARKET", "reason": "OTHER_MARKET"},
        ]

    def test_counts_and_percentages(self):
        summary = A.annotate_actionability(self.rows())
        self.assertEqual(summary["schema"], "SPORTSEDGE_ACTIONABILITY_V1")
        self.assertEqual(summary["total_rows"], 7)
        self.assertEqual(summary["counts"],
                         {"ACTIONABLE": 2, "WATCH": 2, "BLOCKED": 3})
        self.assertEqual(summary["percentages"],
                         {"ACTIONABLE": 28.6, "WATCH": 28.6, "BLOCKED": 42.9})
        self.assertAlmostEqual(sum(summary["percentages"].values()), 100.1,
                               places=0)
        self.assertTrue(summary["research_only"])

    def test_top_blocked_reasons(self):
        summary = A.annotate_actionability(self.rows())
        top = summary["top_blocked_reasons"]
        codes = {t["reason_code"]: t["count"] for t in top}
        self.assertEqual(codes["NO_MODEL_OR_MARKET"], 2)
        self.assertEqual(codes["BLOCKED_PREPRICING_QB_IDENTITY_UNVERIFIED"], 1)
        self.assertLessEqual(len(top), 10)

    def test_rows_annotated_in_place(self):
        rows = self.rows()
        A.annotate_actionability(rows)
        self.assertEqual([r["actionability"] for r in rows],
                         ["ACTIONABLE", "ACTIONABLE", "WATCH", "WATCH",
                          "BLOCKED", "BLOCKED", "BLOCKED"])
        self.assertTrue(all("actionability_detail" in r for r in rows))

    def test_empty_rows(self):
        summary = A.annotate_actionability([])
        self.assertEqual(summary["total_rows"], 0)
        self.assertEqual(summary["percentages"],
                         {"ACTIONABLE": 0.0, "WATCH": 0.0, "BLOCKED": 0.0})
        self.assertEqual(summary["top_blocked_reasons"], [])

    def test_game_freshness_caveat_present(self):
        summary = A.annotate_actionability(self.rows())
        self.assertIn("quote-capture timestamps",
                      summary["game_quote_freshness_caveat"])
        self.assertIn("NOT independently verified-current quotes",
                      summary["game_quote_freshness_caveat"])


if __name__ == "__main__":
    unittest.main()
