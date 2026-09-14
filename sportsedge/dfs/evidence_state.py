from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from sportsedge.dfs.mlb_pitcher_pathset import (
    MlbPitcherPathSetError,
    MlbPitcherPathSetPolicy,
    validate_mlb_pitcher_path_set,
)


@dataclass(frozen=True)
class LaneEvidenceState:
    status: str
    reason: str
    evidence_accruing: bool


def ownership_evidence_state(
    *,
    entered_contests_since_epoch: int,
    complete_exports_frozen: int,
) -> LaneEvidenceState:
    """Separate a real evidence wait from a lane that is not collecting evidence."""
    if entered_contests_since_epoch < 0 or complete_exports_frozen < 0:
        raise ValueError("DFS_OWNERSHIP_EVIDENCE_COUNT_NEGATIVE")
    if complete_exports_frozen > entered_contests_since_epoch:
        raise ValueError("DFS_OWNERSHIP_EXPORT_COUNT_EXCEEDS_ENTERED_CONTESTS")
    if entered_contests_since_epoch == 0:
        return LaneEvidenceState(
            status="NOT_ACCRUING",
            reason="NO_ENTERED_CONTESTS_SINCE_EVIDENCE_EPOCH",
            evidence_accruing=False,
        )
    if complete_exports_frozen == 0:
        return LaneEvidenceState(
            status="EVIDENCE_PENDING",
            reason="ENTERED_CONTEST_EXISTS_BUT_COMPLETE_EXPORT_NOT_FROZEN",
            evidence_accruing=True,
        )
    return LaneEvidenceState(
        status="ACCRUING",
        reason="COMPLETE_ENTERED_CONTEST_EXPORTS_FROZEN",
        evidence_accruing=True,
    )


def mlb_pitcher_upstream_state(
    produced_fields: Iterable[str],
    *,
    path_rows: Iterable[Mapping[str, object]] | None = None,
    path_set_policy: MlbPitcherPathSetPolicy | None = None,
    batter_by_batter_generator: bool | None = None,
    hook_conditioned_on_pitch_count: bool | None = None,
    hook_conditioned_on_runs_allowed: bool | None = None,
    bullpen_remainder_routed: bool | None = None,
    hit_conservation_validated: bool | None = None,
    full_game_continued_after_starter_exit: bool | None = None,
) -> LaneEvidenceState:
    """State whether production paths can honestly support starter DFS accounting.

    Legacy producer booleans remain accepted as call-site metadata for compatibility,
    but they cannot create readiness. Readiness now requires a frozen policy and a
    path-set validation computed from the path distribution itself.
    """
    required = {
        "outs",
        "strikeouts",
        "earned_runs",
        "hits_allowed",
        "walks_allowed",
        "hbp_allowed",
        "starter_exit_batters_faced",
        "starter_exit_pitch_count",
        "bullpen_hits_allowed",
        "opponent_team_hits",
        "lead_at_exit",
        "lead_preserved_to_final",
    }
    fields = {str(field) for field in produced_fields}
    missing = sorted(required - fields)
    if missing:
        return LaneEvidenceState(
            status="BLOCKED",
            reason="UPSTREAM_STATE_MISSING:" + ",".join(missing),
            evidence_accruing=False,
        )

    if path_rows is None or path_set_policy is None:
        return LaneEvidenceState(
            status="BLOCKED",
            reason="UPSTREAM_PATH_SET_VALIDATION_MISSING",
            evidence_accruing=False,
        )

    try:
        validation = validate_mlb_pitcher_path_set(path_rows, path_set_policy)
    except MlbPitcherPathSetError as exc:
        return LaneEvidenceState(
            status="BLOCKED",
            reason="UPSTREAM_PATH_SET_VALIDATION_ERROR:" + str(exc),
            evidence_accruing=False,
        )

    if not validation.passed:
        return LaneEvidenceState(
            status="BLOCKED",
            reason="UPSTREAM_PATH_SET_VALIDATION_FAILED:" + ",".join(validation.failures),
            evidence_accruing=False,
        )

    return LaneEvidenceState(
        status="READY_FOR_PATH_VALIDATION",
        reason=(
            "UPSTREAM_PATH_SET_BEHAVIOR_COMPUTED_AND_VALIDATED:"
            f"{validation.policy_id}:{validation.policy_sha256}:{validation.path_set_sha256}"
        ),
        evidence_accruing=True,
    )
