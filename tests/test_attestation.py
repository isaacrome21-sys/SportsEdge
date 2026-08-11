import json
import tempfile
import unittest
from pathlib import Path

from sportsedge.attestation import AttestationError, validate_attestation


class AttestationTests(unittest.TestCase):
    def test_hits_requires_exact_fixture_engine_feature_and_ci_identity(self):
        good = {
            "market": "HITS", "verdict": "PASS", "engine_version": "hits_engine_v1.2",
            "feature_version": "hits_features_v1",
            "fixture_sha256": "8c15e196efa5fc7ef979d0a9cf5ec113cba54cd756482babc256c44d53642409",
            "ci_commit_sha": "a" * 40, "test_name": "full_holdout_acceptance",
        }
        out = validate_attestation(good)
        self.assertTrue(out["eligible_for_promotion"])
        bad = dict(good); bad["fixture_sha256"] = "0" * 64
        self.assertFalse(validate_attestation(bad)["eligible_for_promotion"])

    def test_total_bases_cannot_promote_without_resolved_fixture_hash(self):
        with self.assertRaises(AttestationError):
            validate_attestation({
                "market": "TOTAL_BASES", "verdict": "PASS",
                "engine_version": "total_bases_engine_v0.2",
                "feature_version": "total_bases_features_v1",
                "fixture_sha256": "0" * 64, "ci_commit_sha": "a" * 40,
                "test_name": "full_holdout_acceptance",
            })

    def test_unknown_market_fails_closed(self):
        with self.assertRaises(AttestationError):
            validate_attestation({"market": "FOO"})


if __name__ == "__main__":
    unittest.main()
