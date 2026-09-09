"""Grouped MLB prop-evidence dependency contract.

This module does not manufacture observations, replay depth, calibration, or
promotion state. Callers must supply explicit readiness for each primary evidence
group from independently captured evidence. Per-market calibration is a separate
consistency check: it may veto readiness but can never satisfy a missing evidence
group.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


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

# Dependencies mirror the current production-candidate engines in
# hitter_joint_engine.py, pitcher_joint_engine.py, first_hr_order_engine.py, and
# pitcher_record_win_engine.py.  All hitter lanes depend on realized PA support.
# Event-count lanes additionally depend on event-type evidence; run/RBI/stolen
# and combination lanes additionally require run-sequence evidence. FIRST_HOME_RUN
# adds the dedicated ordering group. Pitcher outs/record-win are workload lanes;
# event-allowed props require both workload and event-allowed evidence.
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
    """Assess evidence readiness without inferring or counting evidence.

    `calibration_consistent=True` is never evidence.  It only means the separate
    family-level calibration consistency veto did not fail. `None` is fail-closed
    because the consistency check has not been established; False is an explicit
    failure. Missing primary evidence groups always remain blockers regardless of
    calibration state.
    """
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
    """Return every market whose dependency graph includes HITTER_PA."""
    return tuple(sorted(
        market for market, groups in MARKET_EVIDENCE_DEPENDENCIES.items()
        if HITTER_PA in groups
    ))


def dependent_pitcher_markets() -> tuple[str, ...]:
    """Return every market whose dependency graph includes PITCHER_WORKLOAD."""
    return tuple(sorted(
        market for market, groups in MARKET_EVIDENCE_DEPENDENCIES.items()
        if PITCHER_WORKLOAD in groups
    ))
