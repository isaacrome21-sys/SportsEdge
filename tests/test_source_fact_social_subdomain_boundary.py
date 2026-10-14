"""Social-host regression coverage; no activation or pricing authority."""
import unittest
from sportsedge.source_fact_evidence import adjudicate_pregame_fact

CUTOFF = "2026-10-13T18:00:00Z"
DIGEST = "a" * 64

def classify(host, kind, channel):
    row = {"source_id": "s", "source_url": "https://" + host + "/post",
           "source_kind": kind, "anchor_sha256": DIGEST,
           "raw_sha256": "b" * 64, "event_id": "game-1",
           "subject_id": 17, "fact_kind": "STARTER",
           "value": "ACTIVE", "published_at_utc": "2026-10-13T17:30:00Z",
           "observed_at_utc": "2026-10-13T17:35:00Z",
           "fetched_at_utc": "2026-10-13T17:40:00Z",
           "confirmation": "CONFIRMED" if kind == "OFFICIAL" else "RUMOR"}
    return adjudicate_pregame_fact(
        event_id="game-1", subject_id=17, fact_kind="STARTER",
        cutoff_utc=CUTOFF, evidence=[row],
        source_registry={"s": {"kind": kind, "hosts": [host], "anchor_sha256": DIGEST}},
        search_log=[{"channel": channel, "query": "starter",
                     "search_url": "https://" + host + "/search",
                     "searched_at_utc": "2026-10-13T17:50:00Z"}],
        max_age_seconds=3600)

class SocialSubdomainTests(unittest.TestCase):
    def test_x_subdomain_not_official(self):
        self.assertEqual(classify("mobile.x.com", "OFFICIAL", "OFFICIAL_WEB")["state"], "BLOCKED")

    def test_twitter_subdomain_not_official(self):
        self.assertEqual(classify("mobile.twitter.com", "OFFICIAL", "OFFICIAL_WEB")["state"], "BLOCKED")

    def test_x_subdomain_is_social_search(self):
        result = classify("mobile.x.com", "SOCIAL", "X")
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(result["search_channels_pre_cutoff"], ["X"])
        self.assertFalse(result["source_authenticity_verified"])

    def test_lookalike_not_social(self):
        result = classify("notx.com", "OFFICIAL", "OFFICIAL_WEB")
        self.assertEqual(result["state"], "SUPPORTED_RESEARCH_ONLY")
        self.assertEqual(result["search_channels_pre_cutoff"], ["OFFICIAL_WEB"])
        self.assertFalse(result["pricing_authority"])

if __name__ == "__main__":
    unittest.main()
