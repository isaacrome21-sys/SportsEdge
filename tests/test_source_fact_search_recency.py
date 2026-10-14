"""Pregame search declarations must be recent and never confer authority."""
import unittest
from sportsedge.source_fact_evidence import adjudicate_pregame_fact

class SearchRecencyTests(unittest.TestCase):
    def decide(self, web_time, x_time):
        return adjudicate_pregame_fact(
            event_id="fixture-1", subject_id=1, fact_kind="STARTER",
            cutoff_utc="2026-10-13T23:00:00Z", evidence=[],
            source_registry={"league": {"kind": "OFFICIAL", "hosts": ["mlb.com"]}},
            search_log=[
                {"channel": "OFFICIAL_WEB", "query": "starter",
                 "search_url": "https://mlb.com/", "searched_at_utc": web_time},
                {"channel": "X", "query": "starter",
                 "search_url": "https://x.com/", "searched_at_utc": x_time}],
            max_age_seconds=3600)

    def test_stale_both_missing(self):
        result = self.decide("2026-10-13T18:00:00Z", "2026-10-13T18:00:00Z")
        self.assertEqual(result["missing_search_channels"], ["OFFICIAL_WEB", "X"])
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertFalse(result["play_authority"])

    def test_recent_declarations_not_authenticated(self):
        result = self.decide("2026-10-13T22:30:00Z", "2026-10-13T22:31:00Z")
        self.assertEqual(result["missing_search_channels"], [])
        self.assertFalse(result["search_execution_verified"])
        self.assertFalse(result["source_authenticity_verified"])
        self.assertFalse(result["pricing_authority"])

    def test_exact_boundary(self):
        result = self.decide("2026-10-13T22:00:00Z", "2026-10-13T23:00:00Z")
        self.assertEqual(result["search_channels_pre_cutoff"], ["OFFICIAL_WEB", "X"])

    def test_future_search_excluded(self):
        result = self.decide("2026-10-13T23:00:01Z", "2026-10-13T22:30:00Z")
        self.assertEqual(result["missing_search_channels"], ["OFFICIAL_WEB"])
