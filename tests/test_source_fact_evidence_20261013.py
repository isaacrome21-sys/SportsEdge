"""Synthetic pregame source-evidence regression checks; no live receipts or prices."""
import unittest

from sportsedge.source_fact_evidence import adjudicate_pregame_fact

CUTOFF = "2026-10-13T18:00:00Z"
HASH = "a" * 64
REGISTRY = {
    "league": {"kind": "OFFICIAL", "hosts": ["mlb.com"], "anchor_sha256": HASH},
    "reporter": {"kind": "VERIFIED_REPORTER", "hosts": ["news.example"], "anchor_sha256": HASH},
    "social": {"kind": "SOCIAL", "hosts": ["x.com"], "anchor_sha256": HASH},
}


def source(source_id="league", value="ACTIVE", published="2026-10-13T17:30:00Z",
           observed="2026-10-13T17:35:00Z", fetched="2026-10-13T17:40:00Z",
           confirmation="CONFIRMED"):
    host = {"league": "mlb.com", "reporter": "news.example", "social": "x.com"}[source_id]
    return {
        "source_id": source_id, "source_url": "https://" + host + "/source",
        "source_kind": REGISTRY[source_id]["kind"], "anchor_sha256": HASH,
        "raw_sha256": "b" * 64, "event_id": "game-1", "subject_id": 17,
        "fact_kind": "STARTER", "value": value, "published_at_utc": published,
        "observed_at_utc": observed, "fetched_at_utc": fetched,
        "confirmation": confirmation,
    }


def decide(*evidence, search_log=()):
    return adjudicate_pregame_fact(
        event_id="game-1", subject_id=17, fact_kind="STARTER",
        cutoff_utc=CUTOFF, evidence=list(evidence), source_registry=REGISTRY,
        search_log=search_log, max_age_seconds=3600,
    )


class PregameEvidenceTests(unittest.TestCase):
    def test_official_confirmed_is_research_only(self):
        result = decide(source())
        self.assertEqual(result["state"], "SUPPORTED_RESEARCH_ONLY")
        self.assertFalse(result["pricing_authority"])
        self.assertFalse(result["play_authority"])
        self.assertFalse(result["source_authenticity_verified"])
        item = result["accepted_sources"][0]
        self.assertEqual(item["published_at_utc"], "2026-10-13T17:30:00+00:00")
        self.assertEqual(item["observed_at_utc"], "2026-10-13T17:35:00+00:00")
        self.assertEqual(item["fetched_at_utc"], "2026-10-13T17:40:00+00:00")
        self.assertEqual(item["pre_event_cutoff_utc"], "2026-10-13T18:00:00+00:00")

    def test_refetched_old_publication_remains_stale(self):
        result = decide(source(published="2026-10-10T17:30:00Z"))
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(result["reason"], "SOURCE_EVIDENCE_STALE")

    def test_refetched_old_observation_remains_stale(self):
        result = decide(source(observed="2026-10-10T17:35:00Z"))
        self.assertEqual(result["state"], "UNKNOWN")

    def test_post_cutoff_receipt_is_blocked(self):
        result = decide(source(fetched="2026-10-13T18:01:00Z"))
        self.assertEqual(result["state"], "BLOCKED")

    def test_conflicting_confirmed_sources_block(self):
        result = decide(source(), source("reporter", value="OUT"))
        self.assertEqual(result["reason"], "CONTRADICTORY_CREDIBLE_SOURCES")
        self.assertIsNone(result["value"])

    def test_social_claim_never_self_confirms(self):
        result = decide(source("social"))
        self.assertEqual(result["state"], "BLOCKED")
        self.assertFalse(result["pricing_authority"])

    def test_unconfirmed_social_claim_remains_unknown(self):
        result = decide(source("social", confirmation="RUMOR"))
        self.assertEqual(result["state"], "UNKNOWN")

    def test_search_log_channels_recorded_not_treated_as_proof(self):
        log = [
            {"channel": "OFFICIAL_WEB", "query": "starter", "search_url": "https://mlb.com/",
             "searched_at_utc": "2026-10-13T17:50:00Z"},
            {"channel": "X", "query": "starter", "search_url": "https://x.com/",
             "searched_at_utc": "2026-10-13T17:51:00Z"},
        ]
        result = decide(search_log=log)
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(result["search_channels_pre_cutoff"], ["OFFICIAL_WEB", "X"])
        self.assertFalse(result["source_authenticity_verified"])

    def test_unknown_source_host_rejected(self):
        row = source()
        row["source_url"] = "https://attacker.example/false"
        self.assertEqual(decide(row)["state"], "BLOCKED")

    def test_unaware_time_rejected(self):
        row = source(published="2026-10-13T17:30:00")
        self.assertEqual(decide(row)["state"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
