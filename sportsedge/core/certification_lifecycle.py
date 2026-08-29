"""Fail-closed certification lifecycle shared by SportsEdge sports.

Statistical health checks are not sufficient when the sport or settlement regime
changes. A material structural break revokes certification immediately and requires a
new versioned replay before re-promotion.
"""
from __future__ import annotations

from dataclasses import dataclass


class CertificationLifecycleError(ValueError):
    pass


ALLOWED_STATUSES = frozenset({
    "NO_ENGINE",
    "EXPERIMENTAL",
    "EVIDENCE_INCOMPLETE",
    "VALIDATED_MODEL",
    "READY_FOR_POLICY",
    "OFFICIAL",
    "REVOKED",
})

MATERIAL_STRUCTURAL_CHANGE_CODES = frozenset({
    "SCORING_RULE_CHANGE",
    "OVERTIME_FORMAT_CHANGE",
    "ROSTER_ELIGIBILITY_OR_TRANSFER_REGIME_CHANGE",
    "SCHEDULE_OR_SEASON_FORMAT_CHANGE",
    "MARKET_SETTLEMENT_RULE_CHANGE",
    "MATERIAL_DATA_DEFINITION_CHANGE",
})


@dataclass(frozen=True)
class StructuralChangeEvent:
    event_id: str
    sport: str
    effective_at: str
    change_code: str
    material: bool
    evidence_ref: str

    def validate(self) -> "StructuralChangeEvent":
        if not self.event_id or not self.sport or not self.effective_at or not self.evidence_ref:
            raise CertificationLifecycleError("STRUCTURAL_EVENT_FIELDS_REQUIRED")
        if self.change_code not in MATERIAL_STRUCTURAL_CHANGE_CODES:
            raise CertificationLifecycleError("STRUCTURAL_CHANGE_CODE_INVALID")
        if type(self.material) is not bool:
            raise CertificationLifecycleError("STRUCTURAL_MATERIAL_BOOL_REQUIRED")
        return self


@dataclass(frozen=True)
class RepromotionEvidence:
    new_model_or_policy_version: bool
    new_policy_bundle_sha_valid: bool
    full_pit_replay_complete: bool
    truth_gate_official: bool
    required_attestations_pass: bool
    invalidated_rows_excluded: bool

    def validate(self) -> "RepromotionEvidence":
        for name, value in self.__dict__.items():
            if type(value) is not bool:
                raise CertificationLifecycleError(f"{name}:BOOL_REQUIRED")
        return self

    @property
    def complete(self) -> bool:
        self.validate()
        return all(self.__dict__.values())


def apply_structural_change(current_status: str, event: StructuralChangeEvent) -> str:
    status = str(current_status).upper()
    if status not in ALLOWED_STATUSES:
        raise CertificationLifecycleError("CERTIFICATION_STATUS_INVALID")
    event.validate()
    if event.material:
        return "REVOKED"
    return status


def repromote_from_revoked(current_status: str, evidence: RepromotionEvidence) -> str:
    status = str(current_status).upper()
    if status != "REVOKED":
        raise CertificationLifecycleError("REPROMOTION_REQUIRES_REVOKED_STATUS")
    if not evidence.complete:
        raise CertificationLifecycleError("REPROMOTION_EVIDENCE_INCOMPLETE")
    return "OFFICIAL"
