"""X/social host identity cannot be upgraded to official evidence by a declared pin."""
import unittest
from sportsedge.source_fact_evidence import adjudicate_pregame_fact

CUTOFF = "2026-10-13T18:00:00Z"
HASH = "a" * 64

def row(kind):
    return dict(source_id="spoof", source_url="https://x.com/claimed_official",
                source_kind=kind, anchor_sha256=HASH, raw_sha256="b" * 64,
                event_id="game-1", subject_id=17, fact_kind="STARTER",
                value="ACTIVE", published_at_utc="2026-10-13T17:30:00Z",
                observed_at_utc="2026-10-13T17:35:00Z",
                fetched_at_utc="2026-10-13T17:40:00Z",
                confirmation="CONFIRMED")

class XHostBoundaryTests(unittest.TestCase):
    def test_x_host_cannot_be_declared_official_or_verified_reporter(self):
        for kind in ("OFFICIAL", "VERIFIED_REPORTER"):
            with self.subTest(kind=kind):
                result = adjudicate_pregame_fact(
                    event_id="game-1", subject_id=17, fact_kind="STARTER",
                    cutoff_utc=CUTOFF, evidence=[row(kind)],
                    source_registry={"spoof": {"kind": kind, "hosts": ["x.com"],
                                               "anchor_sha256": HASH}})
                self.assertEqual(result["state"], "BLOCKED")
                self.assertEqual(result["reason"], "INVALID_OR_POST_CUTOFF_EVIDENCE")
                self.assertFalse(result["pricing_authority"])
                self.assertFalse(result["play_authority"])

    def test_x_rumor_remains_unknown(self):
        social = row("SOCIAL")
        social["confirmation"] = "RUMOR"
        result = adjudicate_pregame_fact(
            event_id="game-1", subject_id=17, fact_kind="STARTER",
            cutoff_utc=CUTOFF, evidence=[social],
            source_registry={"spoof": {"kind": "SOCIAL", "hosts": ["x.com"],
                                       "anchor_sha256": HASH}})
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertFalse(result["play_authority"])
