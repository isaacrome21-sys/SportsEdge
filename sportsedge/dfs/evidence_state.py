from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


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
    batter_by_batter_generator: bool,
    bullpen_remainder_routed: bool,
    full_game_continued_after_starter_exit: bool,
) -> LaneEvidenceState:
    """State whether production paths can honestly support starter DFS accounting."""
    required = {
        "outs",
        "strikeouts",
        "earned_runs",
        "hits_allowed",
        "walks_allowed",
        "hbp_allowed",
        "starter_exit_batters_faced",
        "starter_exit_pitch_count",
        "starter_scoped_events",
        "lead_at_exit",
        "lead_preserved_to_final",
    }
    fields = {str(field) for field in produced_fields}
    missing = sorted(required - fields)
    structural = []
    if not batter_by_batter_generator:
        structural.append("BATTER_BY_BATTER_GENERATOR")
    if not bullpen_remainder_routed:
        structural.append("BULLPEN_REMAINDER_ROUTING")
    if not full_game_continued_after_starter_exit:
        structural.append("POST_EXIT_FULL_GAME_CONTINUATION")
    defects = [*missing, *structural]
    if defects:
        return LaneEvidenceState(
            status="BLOCKED",
            reason="UPSTREAM_STATE_MISSING:" + ",".join(defects),
            evidence_accruing=False,
        )
    return LaneEvidenceState(
        status="READY_FOR_PATH_VALIDATION",
        reason="UPSTREAM_STARTER_EXIT_STATE_AVAILABLE",
        evidence_accruing=True,
    )
