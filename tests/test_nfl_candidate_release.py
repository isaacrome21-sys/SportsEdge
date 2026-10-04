from __future__ import annotations

import copy
import unittest

from sportsedge.sports.nfl.candidate_release import (
    NFLCandidateReleaseError,
    STATUS,
    build_candidate_release_proposal,
    canonical_payload_sha256,
    validate_non_authoritative_release_proposal,
)

CODE_SHA = "a" * 40
SOURCE_SHA = "b" * 64
PREREG_SHA = "c" * 64


def _evidence() -> dict:
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
        "model_id": "nfl_v2j_conditioned_drive_regime_candidate",
        "distribution_contract": "NFL_M2_V2J_CONDITIONED_DRIVE_SHARED_ENV_V1",
        "event_contract": "NFL_M2_V2H_DRIVE_EVENT_V1",
        "source_manifest_sha256": SOURCE_SHA,
        "candidate_historical_evidence": {
            "spread": {"historical_predictive_pass": True},
            "total": {"historical_predictive_pass": True},
        },
    }


def _proposal(evidence: dict | None = None) -> dict:
    candidate = _evidence() if evidence is None else evidence
    return build_candidate_release_proposal(
        candidate,
        candidate_evidence_sha256=canonical_payload_sha256(candidate),
        preregistration_sha256=PREREG_SHA,
        code_git_sha=CODE_SHA,
        source_manifest_sha256=SOURCE_SHA,
        proposal_id="synthetic-v2j-release-review",
    )


class NFLCandidateReleaseProposalTests(unittest.TestCase):
    def test_valid_readout_builds_zero_authority_human_review_proposal(self):
        proposal = _proposal()
        self.assertEqual(proposal["status"], STATUS)
        self.assertTrue(proposal["human_review_required"])
        self.assertFalse(proposal["selected_for_production"])
        self.assertIsNone(proposal["production_release_identity"])
        self.assertFalse(proposal["frozen_artifact_binding"])
        self.assertFalse(proposal["activation_implemented"])
        self.assertFalse(proposal["promotion_authority"])
        self.assertFalse(proposal["model_p_authority"])
        self.assertFalse(proposal["staking_authority"])
        self.assertFalse(proposal["official_authority"])
        self.assertTrue(proposal["forward_clv_must_start_after_freeze"])
        self.assertFalse(proposal["historical_or_backfilled_clv_allowed"])
        self.assertEqual(proposal["candidate"]["code_git_sha"], CODE_SHA)
        self.assertEqual(proposal["candidate"]["source_manifest_sha256"], SOURCE_SHA)
        self.assertEqual(proposal["candidate"]["preregistration_sha256"], PREREG_SHA)
        self.assertEqual(
            proposal["candidate"]["untouched_readout_sha256"],
            canonical_payload_sha256(_evidence()),
        )
        self.assertEqual(validate_non_authoritative_release_proposal(proposal), proposal)

    def test_promoted_label_alone_cannot_enter_release_bridge(self):
        evidence = _evidence()
        evidence["status"] = "PROMOTED"
        with self.assertRaisesRegex(
            NFLCandidateReleaseError,
            "NFL_CANDIDATE_RELEASE_READOUT_STATUS_INVALID",
        ):
            _proposal(evidence)

    def test_candidate_must_still_have_zero_authority(self):
        for field in (
            "promotion_eligible",
            "promotion_authority",
            "model_p_authority",
            "official_status_granted",
            "production_registry_consumes_this_artifact",
        ):
            evidence = _evidence()
            evidence[field] = True
            with self.subTest(field=field), self.assertRaisesRegex(
                NFLCandidateReleaseError,
                "NFL_CANDIDATE_RELEASE_ZERO_AUTHORITY_REQUIRED",
            ):
                _proposal(evidence)

    def test_post_readout_retuning_cannot_be_smuggled_into_release(self):
        evidence = _evidence()
        evidence["post_readout_retuning_allowed"] = True
        with self.assertRaisesRegex(
            NFLCandidateReleaseError,
            "NFL_CANDIDATE_RELEASE_POST_READOUT_RETUNING_FORBIDDEN",
        ):
            _proposal(evidence)

    def test_source_manifest_must_match_untouched_readout(self):
        evidence = _evidence()
        with self.assertRaisesRegex(
            NFLCandidateReleaseError,
            "NFL_CANDIDATE_RELEASE_SOURCE_MANIFEST_MISMATCH",
        ):
            build_candidate_release_proposal(
                evidence,
                candidate_evidence_sha256=canonical_payload_sha256(evidence),
                preregistration_sha256=PREREG_SHA,
                code_git_sha=CODE_SHA,
                source_manifest_sha256="d" * 64,
                proposal_id="bad-source",
            )

    def test_changed_readout_bytes_fail_hash_binding(self):
        evidence = _evidence()
        original_sha = canonical_payload_sha256(evidence)
        evidence["candidate_historical_evidence"]["spread"]["historical_predictive_pass"] = False
        with self.assertRaisesRegex(
            NFLCandidateReleaseError,
            "NFL_CANDIDATE_RELEASE_EVIDENCE_SHA256_MISMATCH",
        ):
            build_candidate_release_proposal(
                evidence,
                candidate_evidence_sha256=original_sha,
                preregistration_sha256=PREREG_SHA,
                code_git_sha=CODE_SHA,
                source_manifest_sha256=SOURCE_SHA,
                proposal_id="tampered-readout",
            )

    def test_missing_candidate_identity_fails_closed(self):
        for field, message in (
            ("model_id", "MODEL_ID_REQUIRED"),
            ("distribution_contract", "DISTRIBUTION_CONTRACT_REQUIRED"),
            ("event_contract", "EVENT_CONTRACT_REQUIRED"),
        ):
            evidence = _evidence()
            evidence[field] = ""
            with self.subTest(field=field), self.assertRaisesRegex(
                NFLCandidateReleaseError,
                message,
            ):
                _proposal(evidence)

    def test_proposal_mutation_cannot_self_activate(self):
        for field, value, message in (
            ("selected_for_production", True, "SELECTION_NOT_ALLOWED"),
            ("production_release_identity", {"model_id": "laundered"}, "PRODUCTION_IDENTITY_NOT_ALLOWED"),
            ("frozen_artifact_binding", True, "FREEZE_NOT_ALLOWED"),
            ("activation_implemented", True, "ACTIVATION_NOT_ALLOWED"),
            ("promotion_authority", True, "AUTHORITY_NOT_ALLOWED"),
            ("model_p_authority", True, "AUTHORITY_NOT_ALLOWED"),
            ("staking_authority", True, "AUTHORITY_NOT_ALLOWED"),
            ("official_authority", True, "AUTHORITY_NOT_ALLOWED"),
            ("historical_or_backfilled_clv_allowed", True, "BACKFILL_FORBIDDEN"),
        ):
            proposal = copy.deepcopy(_proposal())
            proposal[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                NFLCandidateReleaseError,
                message,
            ):
                validate_non_authoritative_release_proposal(proposal)


if __name__ == "__main__":
    unittest.main()
