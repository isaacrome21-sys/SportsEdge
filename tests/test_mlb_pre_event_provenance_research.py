"""Synthetic checks for MLB research-only pre-event provenance."""
import unittest
from sportsedge.mlb_pre_event_provenance_research import audit_pre_event_fact

CUTOFF = "2026-10-14T19:00:00Z"

def item(url, channel, kind, claim="STARTING", pub="2026-10-14T17:00:00Z", obs="2026-10-14T18:00:00Z"):
    return {"source_url": url, "channel": channel, "source_class": kind,
            "claim": claim, "published_at_utc": pub, "observed_at_utc": obs}

def check(rows):
    return audit_pre_event_fact("event-1:starter", CUTOFF, rows)

class ProvenanceTests(unittest.TestCase):
    def test_no_promotion_even_with_two_channels(self):
        result = check([item("https://www.mlb.com/news", "WEB", "OFFICIAL"),
                        item("https://x.com/club/status/1", "X", "RUMOR")])
        self.assertEqual(result["resolved_status"], "UNKNOWN")
        self.assertFalse(result["play_authority"])
        self.assertFalse(result["market_probability_verified"])
        self.assertEqual(result["candidate_claim"], "STARTING")

    def test_web_only_requires_x(self):
        result = check([item("https://mlb.com/news", "WEB", "OFFICIAL")])
        self.assertEqual(result["blocker"], "WEB_AND_X_COVERAGE_REQUIRED")

    def test_x_subdomain_cannot_be_primary(self):
        result = check([item("https://mobile.x.com/club/status/1", "X", "OFFICIAL"),
                        item("https://mlb.com/news", "WEB", "OTHER")])
        self.assertEqual(result["blocker"], "OFFICIAL_PRIMARY_MISSING")

    def test_conflicting_claims_refused(self):
        result = check([item("https://mlb.com/news", "WEB", "OFFICIAL"),
                        item("https://twitter.com/reporter/status/2", "X", "VERIFIED_REPORTER", "OUT")])
        self.assertEqual(result["blocker"], "CONTRADICTORY_CLAIMS")
        self.assertEqual(result["resolved_status"], "UNKNOWN")

    def test_stale_and_post_cutoff_excluded(self):
        result = check([item("https://mlb.com/news", "WEB", "OFFICIAL",
                             pub="2026-10-12T12:00:00Z", obs="2026-10-12T13:00:00Z"),
                        item("https://x.com/club/status/2", "X", "RUMOR",
                             pub="2026-10-14T19:01:00Z", obs="2026-10-14T19:02:00Z")])
        self.assertEqual(result["timely_channels"], [])
        self.assertEqual([x["evidence_state"] for x in result["observations"]],
                         ["STALE", "POST_CUTOFF_OR_CLOCK_CONFLICT"])

    def test_lookalike_and_channel_mismatch(self):
        for url, channel in (("https://mobile.x.com/club", "WEB"),
                             ("https://x.com.example.org/club", "X"),
                             ("https://notx.com/club", "X")):
            with self.subTest(url=url), self.assertRaises(ValueError):
                check([item(url, channel, "OFFICIAL")])

    def test_trailing_dot_social(self):
        result = check([item("https://mlb.com/news", "WEB", "OFFICIAL"),
                        item("https://mobile.twitter.com./club", "X", "RUMOR")])
        self.assertEqual(result["timely_channels"], ["WEB", "X"])

if __name__ == "__main__":
    unittest.main()
