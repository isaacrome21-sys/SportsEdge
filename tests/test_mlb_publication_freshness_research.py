"""Synthetic pre-event publication freshness regressions; research-only."""
import unittest
from sportsedge.mlb_pre_event_provenance_research import audit_pre_event_fact

CUTOFF = "2026-10-14T19:00:00Z"


def row(url, channel, source_class, published, observed="2026-10-14T18:55:00Z"):
    return {
        "source_url": url, "channel": channel, "source_class": source_class,
        "claim": "STARTING", "published_at_utc": published,
        "observed_at_utc": observed,
    }


class PublicationFreshnessTests(unittest.TestCase):
    def test_old_official_publication_not_refreshed_by_new_observation(self):
        evidence = [
            row("https://www.mlb.com/news", "WEB", "OFFICIAL", "2026-10-12T18:00:00Z"),
            row("https://x.com/reporter/status/1", "X", "VERIFIED_REPORTER",
                "2026-10-14T18:45:00Z"),
        ]
        result = audit_pre_event_fact("fixture:starter", CUTOFF, evidence)
        self.assertEqual(result["observations"][0]["evidence_state"], "STALE")
        self.assertEqual(result["blocker"], "OFFICIAL_PRIMARY_MISSING")
        self.assertIsNone(result["candidate_claim"])
        self.assertFalse(result["play_authority"])

    def test_old_x_publication_not_refreshed_by_new_observation(self):
        evidence = [
            row("https://www.mlb.com/news", "WEB", "OFFICIAL", "2026-10-14T18:45:00Z"),
            row("https://x.com/reporter/status/1", "X", "VERIFIED_REPORTER",
                "2026-10-12T18:00:00Z"),
        ]
        result = audit_pre_event_fact("fixture:starter", CUTOFF, evidence)
        self.assertEqual(result["observations"][1]["evidence_state"], "STALE")
        self.assertEqual(result["blocker"], "WEB_AND_X_COVERAGE_REQUIRED")
        self.assertIsNone(result["candidate_claim"])

    def test_recent_publication_and_observation_are_only_candidates(self):
        evidence = [
            row("https://www.mlb.com/news", "WEB", "OFFICIAL", "2026-10-14T18:45:00Z"),
            row("https://x.com/reporter/status/1", "X", "VERIFIED_REPORTER",
                "2026-10-14T18:45:00Z"),
        ]
        result = audit_pre_event_fact("fixture:starter", CUTOFF, evidence)
        self.assertEqual(result["blocker"], "SOURCE_AUTHENTICITY_NOT_INDEPENDENTLY_VERIFIED")
        self.assertEqual(result["candidate_claim"], "STARTING")
        self.assertEqual(result["resolved_status"], "UNKNOWN")
        self.assertFalse(result["pricing_authority"])

    def test_future_publication_stays_refused(self):
        evidence = [
            row("https://www.mlb.com/news", "WEB", "OFFICIAL", "2026-10-14T19:01:00Z",
                observed="2026-10-14T19:02:00Z"),
        ]
        result = audit_pre_event_fact("fixture:starter", CUTOFF, evidence)
        self.assertEqual(result["observations"][0]["evidence_state"],
                         "POST_CUTOFF_OR_CLOCK_CONFLICT")
        self.assertIsNone(result["candidate_claim"])


if __name__ == "__main__":
    unittest.main()
