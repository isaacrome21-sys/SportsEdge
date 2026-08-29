from __future__ import annotations

import unittest

from sportsedge.core.certification_lifecycle import (
    CertificationLifecycleError,
    RegimeBoundary,
    RepromotionEvidence,
    StructuralChangeEvent,
    apply_structural_change,
    repromote_from_revoked,
)


SHA_A = "a" * 64
SHA_B = "b" * 64


def boundary(**overrides):
    values = dict(
        boundary_id="cfb-ot-2026-v1",
        sport="CFB",
        change_code="OVERTIME_FORMAT_CHANGE",
        announced_at="2026-07-01T12:00:00Z",
        effective_at="2026-08-01T00:00:00Z",
        frozen_at="2026-07-15T00:00:00Z",
        source_authority="NCAA",
        evidence_ref="ncaa-rulebook-2026-ot",
        external_evidence_sha=SHA_A,
        policy_bundle_sha=SHA_B,
    )
    values.update(overrides)
    return RegimeBoundary(**values)


def repromotion(**overrides):
    values = dict(
        new_model_or_policy_version=True,
        new_policy_bundle_sha_valid=True,
        full_pit_replay_complete=True,
        truth_gate_official=True,
        required_attestations_pass=True,
        regime_boundary=boundary(),
        replay_started_at="2026-08-29T14:00:00Z",
        included_event_timestamps=(
            "2026-08-01T00:00:00Z",
            "2026-08-15T18:00:00Z",
        ),
        excluded_regime_event_timestamps=(
            "2026-07-15T18:00:00Z",
            "2026-07-31T23:59:59Z",
        ),
    )
    values.update(overrides)
    return RepromotionEvidence(**values)


class StructuralRegimeBoundaryTests(unittest.TestCase):
    def test_material_external_change_revokes_immediately(self):
        event = StructuralChangeEvent(
            event_id="ot-2026",
            sport="CFB",
            announced_at="2026-07-01T12:00:00Z",
            effective_at="2026-08-01T00:00:00Z",
            change_code="OVERTIME_FORMAT_CHANGE",
            material=True,
            source_authority="NCAA",
            evidence_ref="ncaa-rulebook-2026-ot",
            external_evidence_sha=SHA_A,
        )
        self.assertEqual(apply_structural_change("OFFICIAL", event), "REVOKED")

    def test_boundary_must_be_frozen_before_replay(self):
        late = boundary(frozen_at="2026-08-30T00:00:00Z")
        with self.assertRaisesRegex(CertificationLifecycleError, "NOT_FROZEN_BEFORE_REPLAY"):
            repromotion(regime_boundary=late).validate()

    def test_post_effective_bad_row_cannot_be_laundered_as_regime_exclusion(self):
        with self.assertRaisesRegex(CertificationLifecycleError, "PERFORMANCE_BASED_REGIME_ROW_EXCLUSION_FORBIDDEN"):
            repromotion(excluded_regime_event_timestamps=("2026-08-20T00:00:00Z",)).validate()

    def test_pre_effective_row_cannot_enter_new_regime_replay(self):
        with self.assertRaisesRegex(CertificationLifecycleError, "PRE_REGIME_ROW_INCLUDED"):
            repromotion(included_event_timestamps=("2026-07-20T00:00:00Z",)).validate()

    def test_valid_frozen_boundary_allows_repromotion_only_after_all_other_gates(self):
        self.assertEqual(repromote_from_revoked("REVOKED", repromotion()), "OFFICIAL")
        with self.assertRaisesRegex(CertificationLifecycleError, "REPROMOTION_EVIDENCE_INCOMPLETE"):
            repromote_from_revoked("REVOKED", repromotion(truth_gate_official=False))


if __name__ == "__main__":
    unittest.main()
