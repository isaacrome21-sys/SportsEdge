"""Fail-closed certification lifecycle shared by SportsEdge sports.

Statistical health checks are not sufficient when the sport or settlement regime
changes. A material structural break revokes certification immediately. Re-promotion
may only use a pre-specified, externally evidenced regime boundary frozen before replay;
post-hoc season/row exclusion based on performance is forbidden.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from string import hexdigits
from typing import Iterable


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

REGIME_ROW_RULE = "KEEP_EVENT_TS_ON_OR_AFTER_EFFECTIVE_AT"


def _utc(value: str, field: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        raise CertificationLifecycleError(f"{field}:TIMESTAMP_REQUIRED")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CertificationLifecycleError(f"{field}:ISO8601_REQUIRED") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise CertificationLifecycleError(f"{field}:TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def _sha(value: str, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in hexdigits.lower() for ch in text):
        raise CertificationLifecycleError(f"{field}:SHA256_REQUIRED")
    return text


@dataclass(frozen=True)
class StructuralChangeEvent:
    event_id: str
    sport: str
    announced_at: str
    effective_at: str
    change_code: str
    material: bool
    source_authority: str
    evidence_ref: str
    external_evidence_sha: str

    def validate(self) -> "StructuralChangeEvent":
        if not self.event_id or not self.sport or not self.source_authority or not self.evidence_ref:
            raise CertificationLifecycleError("STRUCTURAL_EVENT_FIELDS_REQUIRED")
        _utc(self.announced_at, "announced_at")
        _utc(self.effective_at, "effective_at")
        _sha(self.external_evidence_sha, "external_evidence_sha")
        if self.change_code not in MATERIAL_STRUCTURAL_CHANGE_CODES:
            raise CertificationLifecycleError("STRUCTURAL_CHANGE_CODE_INVALID")
        if type(self.material) is not bool:
            raise CertificationLifecycleError("STRUCTURAL_MATERIAL_BOOL_REQUIRED")
        return self


@dataclass(frozen=True)
class RegimeBoundary:
    """Immutable structural boundary used to define the replay population.

    The boundary is not inferred from model performance. It must point to dated external
    evidence, carry a content hash for that evidence, and be frozen before replay starts.
    Under V1 the new-regime replay population keeps every otherwise-supportable row whose
    event timestamp is on/after the externally effective timestamp. Excluding a row on or
    after that timestamp as a "regime" exclusion is therefore a hard error.
    """

    boundary_id: str
    sport: str
    change_code: str
    announced_at: str
    effective_at: str
    frozen_at: str
    source_authority: str
    evidence_ref: str
    external_evidence_sha: str
    policy_bundle_sha: str
    row_rule: str = REGIME_ROW_RULE

    def validate(self) -> "RegimeBoundary":
        if not self.boundary_id or not self.sport or not self.source_authority or not self.evidence_ref:
            raise CertificationLifecycleError("REGIME_BOUNDARY_FIELDS_REQUIRED")
        if self.change_code not in MATERIAL_STRUCTURAL_CHANGE_CODES:
            raise CertificationLifecycleError("REGIME_BOUNDARY_CHANGE_CODE_INVALID")
        if self.row_rule != REGIME_ROW_RULE:
            raise CertificationLifecycleError("REGIME_BOUNDARY_ROW_RULE_INVALID")
        _utc(self.announced_at, "regime.announced_at")
        _utc(self.effective_at, "regime.effective_at")
        _utc(self.frozen_at, "regime.frozen_at")
        _sha(self.external_evidence_sha, "regime.external_evidence_sha")
        _sha(self.policy_bundle_sha, "regime.policy_bundle_sha")
        return self

    def validate_replay_population(
        self,
        *,
        replay_started_at: str,
        included_event_timestamps: Iterable[str],
        excluded_regime_event_timestamps: Iterable[str],
    ) -> None:
        self.validate()
        replay_start = _utc(replay_started_at, "replay_started_at")
        frozen = _utc(self.frozen_at, "regime.frozen_at")
        effective = _utc(self.effective_at, "regime.effective_at")
        if frozen > replay_start:
            raise CertificationLifecycleError("REGIME_BOUNDARY_NOT_FROZEN_BEFORE_REPLAY")
        included = tuple(_utc(value, "included_event_timestamp") for value in included_event_timestamps)
        excluded = tuple(_utc(value, "excluded_regime_event_timestamp") for value in excluded_regime_event_timestamps)
        if not included:
            raise CertificationLifecycleError("REPROMOTION_REPLAY_POPULATION_EMPTY")
        if any(value < effective for value in included):
            raise CertificationLifecycleError("PRE_REGIME_ROW_INCLUDED")
        if any(value >= effective for value in excluded):
            raise CertificationLifecycleError("PERFORMANCE_BASED_REGIME_ROW_EXCLUSION_FORBIDDEN")


@dataclass(frozen=True)
class RepromotionEvidence:
    new_model_or_policy_version: bool
    new_policy_bundle_sha_valid: bool
    full_pit_replay_complete: bool
    truth_gate_official: bool
    required_attestations_pass: bool
    regime_boundary: RegimeBoundary
    replay_started_at: str
    included_event_timestamps: tuple[str, ...]
    excluded_regime_event_timestamps: tuple[str, ...]

    def validate(self) -> "RepromotionEvidence":
        for name in (
            "new_model_or_policy_version",
            "new_policy_bundle_sha_valid",
            "full_pit_replay_complete",
            "truth_gate_official",
            "required_attestations_pass",
        ):
            if type(getattr(self, name)) is not bool:
                raise CertificationLifecycleError(f"{name}:BOOL_REQUIRED")
        self.regime_boundary.validate_replay_population(
            replay_started_at=self.replay_started_at,
            included_event_timestamps=self.included_event_timestamps,
            excluded_regime_event_timestamps=self.excluded_regime_event_timestamps,
        )
        return self

    @property
    def complete(self) -> bool:
        self.validate()
        return all((
            self.new_model_or_policy_version,
            self.new_policy_bundle_sha_valid,
            self.full_pit_replay_complete,
            self.truth_gate_official,
            self.required_attestations_pass,
        ))


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
