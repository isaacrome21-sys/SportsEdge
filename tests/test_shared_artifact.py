from __future__ import annotations

import unittest

from sportsedge.shared_artifact import (
    assess_market_artifact_attestation,
    freeze_shared_artifact,
)


class SharedArtifactTests(unittest.TestCase):
    def test_artifact_bytes_are_the_freeze_unit(self):
        first = freeze_shared_artifact(b"fitted-model-bytes-v1", artifact_version="M2")
        same = freeze_shared_artifact(b"fitted-model-bytes-v1", artifact_version="M2-renamed")
        changed = freeze_shared_artifact(b"fitted-model-bytes-v2", artifact_version="M2")

        self.assertEqual(first.artifact_sha256, same.artifact_sha256)
        self.assertNotEqual(first.artifact_sha256, changed.artifact_sha256)

    def test_markets_clear_local_blockers_independently_against_same_artifact(self):
        frozen = freeze_shared_artifact(b"fixture-only-shared-model", artifact_version="fixture")
        ready = assess_market_artifact_attestation(
            market="HITS",
            current_artifact_sha256=frozen.artifact_sha256,
            attestation={
                "shared_artifact_sha256": frozen.artifact_sha256,
                "local_blockers": [],
                "forward_capture_declared": True,
            },
        )
        blocked = assess_market_artifact_attestation(
            market="PITCHER_K",
            current_artifact_sha256=frozen.artifact_sha256,
            attestation={
                "shared_artifact_sha256": frozen.artifact_sha256,
                "local_blockers": ["PITCHER_WORKLOAD_EVIDENCE_MISSING"],
                "forward_capture_declared": True,
            },
        )

        self.assertTrue(ready.ready_for_forward_capture)
        self.assertEqual(ready.status, "READY_FOR_FORWARD_CAPTURE")
        self.assertFalse(blocked.ready_for_forward_capture)
        self.assertEqual(blocked.status, "BLOCKED_LOCAL")

    def test_shared_artifact_change_stales_all_old_attestations_until_each_market_rebinds(self):
        old = freeze_shared_artifact(b"fixture-model-old", artifact_version="fixture-old")
        new = freeze_shared_artifact(b"fixture-model-new", artifact_version="fixture-new")
        old_attestation = {
            "shared_artifact_sha256": old.artifact_sha256,
            "local_blockers": [],
            "forward_capture_declared": True,
        }

        for market in ("HITS", "PITCHER_K"):
            stale = assess_market_artifact_attestation(
                market=market,
                current_artifact_sha256=new.artifact_sha256,
                attestation=old_attestation,
            )
            self.assertEqual(stale.status, "STALE_SHARED_ARTIFACT")
            self.assertFalse(stale.ready_for_forward_capture)

        hits_rebound = assess_market_artifact_attestation(
            market="HITS",
            current_artifact_sha256=new.artifact_sha256,
            attestation={
                "shared_artifact_sha256": new.artifact_sha256,
                "local_blockers": [],
                "forward_capture_declared": True,
            },
        )
        pitcher_still_stale = assess_market_artifact_attestation(
            market="PITCHER_K",
            current_artifact_sha256=new.artifact_sha256,
            attestation=old_attestation,
        )

        self.assertTrue(hits_rebound.ready_for_forward_capture)
        self.assertEqual(hits_rebound.status, "READY_FOR_FORWARD_CAPTURE")
        self.assertFalse(pitcher_still_stale.ready_for_forward_capture)
        self.assertEqual(pitcher_still_stale.status, "STALE_SHARED_ARTIFACT")

    def test_forward_capture_must_be_explicit_even_with_no_local_blockers(self):
        frozen = freeze_shared_artifact(b"fixture-model", artifact_version="fixture")
        result = assess_market_artifact_attestation(
            market="HITS",
            current_artifact_sha256=frozen.artifact_sha256,
            attestation={
                "shared_artifact_sha256": frozen.artifact_sha256,
                "local_blockers": [],
                "forward_capture_declared": False,
            },
        )
        self.assertEqual(result.status, "FORWARD_CAPTURE_NOT_DECLARED")
        self.assertFalse(result.ready_for_forward_capture)


if __name__ == "__main__":
    unittest.main()
