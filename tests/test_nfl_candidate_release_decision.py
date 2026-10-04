from __future__ import annotations

import copy
import unittest

from sportsedge.sports.nfl.candidate_release import (
    build_candidate_release_proposal,
    canonical_payload_sha256,
)
from sportsedge.sports.nfl.candidate_release_decision import (
    NFLCandidateReleaseDecisionError,
    STATUS,
    build_candidate_release_decision,
    validate_candidate_release_decision,
)

SOURCE_SHA = "b" * 64
PREREG_SHA = "c" * 64
CODE_SHA = "a" * 40


def evidence(model_id: str = "nfl_v2j_conditioned_drive_regime_candidate") -> dict:
    return {
        "schema_version": 1,
        "status": "FIRST_READOUT_DIAGNOSTIC_ONLY",
        "preregistration_locked": True,
        "post_readout_retuning_allowed": False,
        "promotion_eligible": False,
        "promotion_authority": False,
        "model_p_authority": False,
        "official_status_granted": False,
        "production_registry_consumes_this_artifact": False,
        "model_id": model_id,
        "distribution_contract": "NFL_M2_V2J_CONDITIONED_DRIVE_SHARED_ENV_V1",
        "event_contract": "NFL_M2_V2H_DRIVE_EVENT_V1",
        "source_manifest_sha256": SOURCE_SHA,
    }


def proposal(model_id: str = "nfl_v2j_conditioned_drive_regime_candidate") -> dict:
    e = evidence(model_id)
    return build_candidate_release_proposal(
        e,
        candidate_evidence_sha256=canonical_payload_sha256(e),
        preregistration_sha256=PREREG_SHA,
        code_git_sha=CODE_SHA,
        source_manifest_sha256=SOURCE_SHA,
        proposal_id="release-review",
    )


def decision(model_id: str = "nfl_v2j_conditioned_drive_regime_candidate") -> dict:
    p = proposal(model_id)
    return build_candidate_release_decision(
        p,
        proposal_sha256=canonical_payload_sha256(p),
        reviewer="governance-review",
        review_ticket="issue-608",
        production_release_id="nfl-v2j-release-v1",
    )


class NFLReleaseDecisionTests(unittest.TestCase):
    def test_builds_versioned_zero_authority_release_decision(self):
        row = decision()
        self.assertEqual(row["status"], STATUS)
        self.assertTrue(row["selected_for_production"])
        self.assertEqual(row["production_release_identity"]["release_id"], "nfl-v2j-release-v1")
        self.assertFalse(row["release_artifact_built"])
        self.assertFalse(row["frozen_artifact_binding"])
        self.assertFalse(row["activation_implemented"])
        self.assertFalse(row["promotion_authority"])
        self.assertFalse(row["model_p_authority"])
        self.assertFalse(row["staking_authority"])
        self.assertFalse(row["official_authority"])
        self.assertEqual(validate_candidate_release_decision(row), row)

    def test_proposal_hash_mismatch_fails(self):
        p = proposal()
        with self.assertRaisesRegex(NFLCandidateReleaseDecisionError, "PROPOSAL_SHA256_MISMATCH"):
            build_candidate_release_decision(
                p,
                proposal_sha256="d" * 64,
                reviewer="reviewer",
                review_ticket="issue-608",
                production_release_id="nfl-v2j-release-v1",
            )

    def test_legacy_m2_candidate_identity_cannot_be_laundered(self):
        from sportsedge.sports.nfl.m2 import PRODUCTION_NFL_M2_MODEL_ID
        p = proposal(PRODUCTION_NFL_M2_MODEL_ID)
        with self.assertRaisesRegex(NFLCandidateReleaseDecisionError, "LEGACY_M2_RELABEL_FORBIDDEN"):
            build_candidate_release_decision(
                p,
                proposal_sha256=canonical_payload_sha256(p),
                reviewer="reviewer",
                review_ticket="issue-608",
                production_release_id="nfl-release-v1",
            )

    def test_decision_mutation_cannot_self_activate(self):
        for field in (
            "release_artifact_built",
            "frozen_artifact_binding",
            "activation_implemented",
            "promotion_authority",
            "model_p_authority",
            "staking_authority",
            "official_authority",
            "historical_or_backfilled_clv_allowed",
        ):
            row = copy.deepcopy(decision())
            row[field] = True
            with self.subTest(field=field), self.assertRaisesRegex(
                NFLCandidateReleaseDecisionError, "ZERO_AUTHORITY_REQUIRED"
            ):
                validate_candidate_release_decision(row)

    def test_release_identity_must_preserve_candidate_binding(self):
        row = copy.deepcopy(decision())
        row["production_release_identity"]["distribution_contract"] = "changed"
        with self.assertRaisesRegex(NFLCandidateReleaseDecisionError, "IDENTITY_BINDING_MISMATCH"):
            validate_candidate_release_decision(row)


if __name__ == "__main__":
    unittest.main()
