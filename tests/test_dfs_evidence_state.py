from __future__ import annotations

import pytest

from sportsedge.dfs.evidence_state import (
    mlb_pitcher_upstream_state,
    ownership_evidence_state,
)


_REQUIRED_PITCHER_FIELDS = {
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


def test_ownership_waiting_without_entries_is_not_accruing() -> None:
    state = ownership_evidence_state(
        entered_contests_since_epoch=0,
        complete_exports_frozen=0,
    )
    assert state.status == "NOT_ACCRUING"
    assert state.reason == "NO_ENTERED_CONTESTS_SINCE_EVIDENCE_EPOCH"
    assert state.evidence_accruing is False


def test_entered_contest_can_be_evidence_pending() -> None:
    state = ownership_evidence_state(
        entered_contests_since_epoch=1,
        complete_exports_frozen=0,
    )
    assert state.status == "EVIDENCE_PENDING"
    assert state.evidence_accruing is True


def test_frozen_complete_export_is_accruing() -> None:
    state = ownership_evidence_state(
        entered_contests_since_epoch=2,
        complete_exports_frozen=1,
    )
    assert state.status == "ACCRUING"
    assert state.evidence_accruing is True


def test_ownership_counts_fail_closed() -> None:
    with pytest.raises(ValueError, match="EXCEEDS_ENTERED"):
        ownership_evidence_state(
            entered_contests_since_epoch=1,
            complete_exports_frozen=2,
        )


def test_downstream_fields_alone_do_not_make_mlb_pitcher_lane_ready() -> None:
    state = mlb_pitcher_upstream_state(
        _REQUIRED_PITCHER_FIELDS,
        batter_by_batter_generator=False,
        bullpen_remainder_routed=False,
        full_game_continued_after_starter_exit=False,
    )
    assert state.status == "BLOCKED"
    assert state.reason.startswith("UPSTREAM_STATE_MISSING:")
    assert "BATTER_BY_BATTER_GENERATOR" in state.reason
    assert "BULLPEN_REMAINDER_ROUTING" in state.reason
    assert "POST_EXIT_FULL_GAME_CONTINUATION" in state.reason
    assert state.evidence_accruing is False


def test_mlb_pitcher_lane_requires_structure_and_all_exit_fields() -> None:
    state = mlb_pitcher_upstream_state(
        _REQUIRED_PITCHER_FIELDS,
        batter_by_batter_generator=True,
        bullpen_remainder_routed=True,
        full_game_continued_after_starter_exit=True,
    )
    assert state.status == "READY_FOR_PATH_VALIDATION"
    assert state.evidence_accruing is True
