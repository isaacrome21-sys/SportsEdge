"""Grouped MLB prop-evidence dependency and resolution contract.

This module does not manufacture observations, replay depth, calibration, or
promotion state. Callers must supply explicit readiness for each primary evidence
group from independently captured evidence. Per-market calibration is a separate
consistency check: it may veto readiness but can never satisfy a missing evidence
group.

The checked-in production registry is still governed by the permanent unpromoted
workflow. The strict row evaluator below is intentionally introduced behind that
freeze so negative contracts exist before any freeze-to-gate conversion can use it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Mapping


HITTER_PA = "HITTER_PA"
HITTER_EVENT_TYPE = "HITTER_EVENT_TYPE"
HITTER_RUN_SEQUENCE = "HITTER_RUN_SEQUENCE"
FIRST_HR_ORDERING = "FIRST_HR_ORDERING"
PITCHER_WORKLOAD = "PITCHER_WORKLOAD"
PITCHER_EVENT_ALLOWED = "PITCHER_EVENT_ALLOWED"

EVIDENCE_GROUPS = frozenset({
    HITTER_PA,
    HITTER_EVENT_TYPE,
    HITTER_RUN_SEQUENCE,
    FIRST_HR_ORDERING,
    PITCHER_WORKLOAD,
    PITCHER_EVENT_ALLOWED,
})

MARKET_EVIDENCE_DEPENDENCIES: dict[str, frozenset[str]] = {
    "HITS": frozenset({HITTER_PA, HITTER_EVENT_TYPE}),
    "HOME_RUNS": frozenset({HITTER_PA, HITTER_EVENT_TYPE}),
    "TOTAL_BASES": frozenset({HITTER_PA, HITTER_EVENT_TYPE}),
    "BATTER_BB": frozenset({HITTER_PA, HITTER_EVENT_TYPE}),
    "EXTRA_BASE_HITS": frozenset({HITTER_PA, HITTER_EVENT_TYPE}),
    "SINGLES": frozenset({HITTER_PA, HITTER_EVENT_TYPE}),
    "DOUBLES": frozenset({HITTER_PA, HITTER_EVENT_TYPE}),
    "TRIPLES": frozenset({HITTER_PA, HITTER_EVENT_TYPE}),
    "BATTER_K": frozenset({HITTER_PA, HITTER_EVENT_TYPE}),
    "RBI": frozenset({HITTER_PA, HITTER_EVENT_TYPE, HITTER_RUN_SEQUENCE}),
    "RUNS": frozenset({HITTER_PA, HITTER_EVENT_TYPE, HITTER_RUN_SEQUENCE}),
    "STOLEN_BASES": frozenset({HITTER_PA, HITTER_EVENT_TYPE, HITTER_RUN_SEQUENCE}),
    "HITS_RUNS_RBIS": frozenset({HITTER_PA, HITTER_EVENT_TYPE, HITTER_RUN_SEQUENCE}),
    "HITS_RUNS_STOLEN_BASES": frozenset({HITTER_PA, HITTER_EVENT_TYPE, HITTER_RUN_SEQUENCE}),
    "RUNS_RBIS": frozenset({HITTER_PA, HITTER_EVENT_TYPE, HITTER_RUN_SEQUENCE}),
    "HITS_STOLEN_BASES": frozenset({HITTER_PA, HITTER_EVENT_TYPE, HITTER_RUN_SEQUENCE}),
    "HITS_WALKS_STOLEN_BASES": frozenset({HITTER_PA, HITTER_EVENT_TYPE, HITTER_RUN_SEQUENCE}),
    "FIRST_HOME_RUN": frozenset({HITTER_PA, HITTER_EVENT_TYPE, FIRST_HR_ORDERING}),
    "PITCHER_K": frozenset({PITCHER_WORKLOAD, PITCHER_EVENT_ALLOWED}),
    "PITCHER_OUTS": frozenset({PITCHER_WORKLOAD}),
    "PITCHER_ER": frozenset({PITCHER_WORKLOAD, PITCHER_EVENT_ALLOWED}),
    "PITCHER_HITS_ALLOWED": frozenset({PITCHER_WORKLOAD, PITCHER_EVENT_ALLOWED}),
    "PITCHER_BB": frozenset({PITCHER_WORKLOAD, PITCHER_EVENT_ALLOWED}),
    "PITCHER_HITS_WALKS_ER": frozenset({PITCHER_WORKLOAD, PITCHER_EVENT_ALLOWED}),
    "EITHER_PITCHER_HITS_ALLOWED": frozenset({PITCHER_WORKLOAD, PITCHER_EVENT_ALLOWED}),
    "EITHER_PITCHER_BB": frozenset({PITCHER_WORKLOAD, PITCHER_EVENT_ALLOWED}),
    "EITHER_PITCHER_ER": frozenset({PITCHER_WORKLOAD, PITCHER_EVENT_ALLOWED}),
    "PITCHER_RECORD_WIN": frozenset({PITCHER_WORKLOAD}),
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_GROUP_STATUS = frozenset({"PASS", "MISSING", "BLOCKED"})


class PropEvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class PropEvidenceReadiness:
    market: str
    required_groups: tuple[str, ...]
    missing_groups: tuple[str, ...]
    calibration_consistency: str
    blockers: tuple[str, ...]
    ready_for_forward_capture: bool


@dataclass(frozen=True)
class PropGroupEvidenceValidation:
    group: str
    passed: bool
    blockers: tuple[str, ...]


def expected_market_identities(group: str) -> tuple[str, ...]:
    """Return the exact canonical market set whose dependency graph uses a group."""
    group_name = str(group or "").strip().upper()
    if group_name not in EVIDENCE_GROUPS:
        raise PropEvidenceError(f"unknown evidence group: {group_name or '<EMPTY>'}")
    return tuple(sorted(
        market
        for market, dependencies in MARKET_EVIDENCE_DEPENDENCIES.items()
        if group_name in dependencies
    ))


def _parse_utc_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def evaluate_group_evidence_row(
    *,
    group: str,
    row: Mapping[str, Any],
    as_of_utc: str,
) -> PropGroupEvidenceValidation:
    """Fail-closed evaluation for one future prop-evidence PASS row.

    This evaluator is deliberately stricter than the legacy registry resolver and
    is not yet wired to promotion. A row can pass only when it is complete, fresh,
    bound to the requested evidence component, and bound to the exact canonical
    market identities that consume that component. The existing workflow remains
    the production freeze until a later change explicitly replaces it.
    """
    group_name = str(group or "").strip().upper()
    if group_name not in EVIDENCE_GROUPS:
        raise PropEvidenceError(f"unknown evidence group: {group_name or '<EMPTY>'}")
    if not isinstance(row, Mapping):
        return PropGroupEvidenceValidation(
            group=group_name,
            passed=False,
            blockers=("EVIDENCE_ROW_NOT_OBJECT",),
        )

    blockers: list[str] = []
    status = str(row.get("status") or "MISSING").strip().upper()
    if status != "PASS":
        blockers.append("STATUS_NOT_PASS")

    required_fields = (
        "evidence_sha256",
        "evidence_group",
        "market_identities",
        "captured_at_utc",
        "valid_through_utc",
    )
    for field in required_fields:
        if row.get(field) in (None, "", []):
            blockers.append(f"EVIDENCE_METADATA_INCOMPLETE:{field}")

    digest = str(row.get("evidence_sha256") or "").lower()
    if digest and not _SHA256_RE.fullmatch(digest):
        blockers.append("EVIDENCE_SHA256_INVALID")

    evidence_group = str(row.get("evidence_group") or "").strip().upper()
    if evidence_group and evidence_group != group_name:
        blockers.append("EVIDENCE_GROUP_IDENTITY_MISMATCH")

    identities = row.get("market_identities")
    expected = expected_market_identities(group_name)
    if identities not in (None, "", []):
        if not isinstance(identities, (list, tuple)):
            blockers.append("MARKET_IDENTITY_MISMATCH")
        else:
            normalized = tuple(sorted(str(item or "").strip().upper() for item in identities))
            if normalized != expected or len(set(normalized)) != len(normalized):
                blockers.append("MARKET_IDENTITY_MISMATCH")

    as_of = _parse_utc_timestamp(as_of_utc)
    if as_of is None:
        raise PropEvidenceError("as_of_utc must be an offset-aware ISO-8601 timestamp")
    captured = _parse_utc_timestamp(row.get("captured_at_utc"))
    valid_through = _parse_utc_timestamp(row.get("valid_through_utc"))
    if row.get("captured_at_utc") not in (None, "") and captured is None:
        blockers.append("EVIDENCE_TIMESTAMP_INVALID:captured_at_utc")
    if row.get("valid_through_utc") not in (None, "") and valid_through is None:
        blockers.append("EVIDENCE_TIMESTAMP_INVALID:valid_through_utc")
    if captured is not None and captured > as_of:
        blockers.append("EVIDENCE_CAPTURE_AFTER_AS_OF")
    if captured is not None and valid_through is not None and valid_through <= captured:
        blockers.append("EVIDENCE_VALIDITY_RANGE_INVALID")
    if valid_through is not None and valid_through <= as_of:
        blockers.append("EVIDENCE_STALE")

    return PropGroupEvidenceValidation(
        group=group_name,
        passed=not blockers,
        blockers=tuple(blockers),
    )


def group_state_from_registry(payload: Mapping[str, Any]) -> dict[str, bool]:
    """Resolve primary group readiness from the persisted evidence registry."""
    if not isinstance(payload, Mapping):
        raise PropEvidenceError("prop evidence registry must be a mapping")
    if payload.get("schema_version") != 1:
        raise PropEvidenceError("prop evidence registry schema_version must be 1")
    rows = payload.get("groups")
    if not isinstance(rows, Mapping):
        raise PropEvidenceError("prop evidence registry requires groups object")
    unknown = sorted(set(rows) - EVIDENCE_GROUPS)
    if unknown:
        raise PropEvidenceError(f"unknown evidence groups: {','.join(unknown)}")

    resolved: dict[str, bool] = {}
    for group in EVIDENCE_GROUPS:
        row = rows.get(group)
        if row is None:
            resolved[group] = False
            continue
        if not isinstance(row, Mapping):
            raise PropEvidenceError(f"evidence group {group} row must be an object")
        status = str(row.get("status", "MISSING")).upper()
        if status not in _ALLOWED_GROUP_STATUS:
            raise PropEvidenceError(f"evidence group {group} invalid status {status}")
        if status == "PASS":
            digest = str(row.get("evidence_sha256", "")).lower()
            if not _SHA256_RE.fullmatch(digest):
                raise PropEvidenceError(f"evidence group {group} PASS requires evidence_sha256")
            resolved[group] = True
        else:
            resolved[group] = False
    return resolved


def _normalize_group_state(group_state: Mapping[str, bool]) -> dict[str, bool]:
    if not isinstance(group_state, Mapping):
        raise PropEvidenceError("group_state must be a mapping")
    unknown = sorted(set(group_state) - EVIDENCE_GROUPS)
    if unknown:
        raise PropEvidenceError(f"unknown evidence groups: {','.join(unknown)}")
    normalized: dict[str, bool] = {}
    for group in EVIDENCE_GROUPS:
        value = group_state.get(group, False)
        if not isinstance(value, bool):
            raise PropEvidenceError(f"evidence group {group} readiness must be boolean")
        normalized[group] = value
    return normalized


def assess_prop_evidence(
    *,
    market: str,
    group_state: Mapping[str, bool],
    calibration_consistent: bool | None,
) -> PropEvidenceReadiness:
    """Resolve evidence readiness without inferring or counting evidence."""
    market_name = str(market or "").strip().upper()
    dependencies = MARKET_EVIDENCE_DEPENDENCIES.get(market_name)
    if dependencies is None:
        raise PropEvidenceError(f"UNMAPPED_PROP_MARKET:{market_name or '<EMPTY>'}")
    if calibration_consistent not in {True, False, None}:
        raise PropEvidenceError("calibration_consistent must be True, False, or None")

    normalized = _normalize_group_state(group_state)
    required = tuple(sorted(dependencies))
    missing = tuple(group for group in required if not normalized[group])
    blockers = [f"EVIDENCE_GROUP_MISSING:{group}" for group in missing]

    if calibration_consistent is True:
        calibration_status = "CONSISTENT"
    elif calibration_consistent is False:
        calibration_status = "INCONSISTENT"
        blockers.append("CALIBRATION_CONSISTENCY_FAILED")
    else:
        calibration_status = "NOT_ESTABLISHED"
        blockers.append("CALIBRATION_CONSISTENCY_NOT_ESTABLISHED")

    return PropEvidenceReadiness(
        market=market_name,
        required_groups=required,
        missing_groups=missing,
        calibration_consistency=calibration_status,
        blockers=tuple(blockers),
        ready_for_forward_capture=not blockers,
    )


def dependent_hitter_markets() -> tuple[str, ...]:
    """Return every market whose live dependency graph includes HITTER_PA."""
    return tuple(sorted(
        market for market, groups in MARKET_EVIDENCE_DEPENDENCIES.items()
        if HITTER_PA in groups
    ))


def dependent_pitcher_markets() -> tuple[str, ...]:
    """Return every market whose live dependency graph includes PITCHER_WORKLOAD."""
    return tuple(sorted(
        market for market, groups in MARKET_EVIDENCE_DEPENDENCIES.items()
        if PITCHER_WORKLOAD in groups
    ))