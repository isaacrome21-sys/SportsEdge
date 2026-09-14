from __future__ import annotations

import pytest

from sportsedge.dfs.evidence_state import (
    mlb_pitcher_upstream_state,
    ownership_evidence_state,
)
from sportsedge.dfs.mlb_pitcher_pathset import MlbPitcherPathSetPolicy


_REQUIRED_PITCHER_FIELDS = {
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


def _policy() -> MlbPitcherPathSetPolicy:
    return MlbPitcherPathSetPolicy(
        policy_id="TEST_FROZEN_PATH_SET_V1",
        status="FROZEN",
        min_paths=8,
        p_outs_ge_21_min=0.25,
        p_outs_ge_21_max=0.75,
        min_bullpen_active_fraction=0.50,
        min_lead_divergence_fraction=0.10,
    )


def _valid_rows() -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for i in range(8):
        rows.append(
            {
                "starter_exit_batters_faced": float(32 - i),
                "earned_runs": float(i),
                "outs": float(24 if i < 4 else 18),
                "bullpen_hits_allowed": float(0 if i in (0, 1) else 2),
                "lead_at_exit": float(1 if i in (0, 1, 2, 3) else 0),
                "lead_preserved_to_final": float(0 if i == 0 else (1 if i in (1, 2, 3) else 0)),
            }
        )
    return rows


def test_ownership_waiting_without_entries_is_not_accruing() -> None:
    state = ownership_evidence_state(entered_contests_since_epoch=0, complete_exports_frozen=0)
    assert state.status == "NOT_ACCRUING"
    assert state.reason == "NO_ENTERED_CONTESTS_SINCE_EVIDENCE_EPOCH"
    assert state.evidence_accruing is False


def test_entered_contest_can_be_evidence_pending() -> None:
    state = ownership_evidence_state(entered_contests_since_epoch=1, complete_exports_frozen=0)
    assert state.status == "EVIDENCE_PENDING"
    assert state.evidence_accruing is True


def test_frozen_complete_export_is_accruing() -> None:
    state = ownership_evidence_state(entered_contests_since_epoch=2, complete_exports_frozen=1)
    assert state.status == "ACCRUING"
    assert state.evidence_accruing is True


def test_ownership_counts_fail_closed() -> None:
    with pytest.raises(ValueError, match="EXCEEDS_ENTERED"):
        ownership_evidence_state(entered_contests_since_epoch=1, complete_exports_frozen=2)


def test_downstream_fields_and_behavior_flags_alone_cannot_make_pitcher_lane_ready() -> None:
    state = mlb_pitcher_upstream_state(
        _REQUIRED_PITCHER_FIELDS,
        batter_by_batter_generator=True,
        hook_conditioned_on_pitch_count=True,
        hook_conditioned_on_runs_allowed=True,
        bullpen_remainder_routed=True,
        hit_conservation_validated=True,
        full_game_continued_after_starter_exit=True,
    )
    assert state.status == "BLOCKED"
    assert state.reason == "UPSTREAM_PATH_SET_VALIDATION_MISSING"
    assert state.evidence_accruing is False


def test_computed_valid_path_set_can_make_pitcher_lane_ready() -> None:
    state = mlb_pitcher_upstream_state(
        _REQUIRED_PITCHER_FIELDS,
        path_rows=_valid_rows(),
        path_set_policy=_policy(),
        batter_by_batter_generator=True,
        hook_conditioned_on_pitch_count=True,
        hook_conditioned_on_runs_allowed=True,
        bullpen_remainder_routed=True,
        hit_conservation_validated=True,
        full_game_continued_after_starter_exit=True,
    )
    assert state.status == "READY_FOR_PATH_VALIDATION"
    assert state.reason.startswith("UPSTREAM_PATH_SET_BEHAVIOR_COMPUTED_AND_VALIDATED:")
    assert state.evidence_accruing is True


def test_all_complete_game_path_set_is_blocked_even_when_behavior_flags_claim_true() -> None:
    rows = [
        {
            "starter_exit_batters_faced": 38.0,
            "earned_runs": float(i % 5),
            "outs": 27.0,
            "bullpen_hits_allowed": 0.0,
            "lead_at_exit": 1.0,
            "lead_preserved_to_final": 1.0,
        }
        for i in range(8)
    ]
    state = mlb_pitcher_upstream_state(
        _REQUIRED_PITCHER_FIELDS,
        path_rows=rows,
        path_set_policy=_policy(),
        batter_by_batter_generator=True,
        hook_conditioned_on_pitch_count=True,
        hook_conditioned_on_runs_allowed=True,
        bullpen_remainder_routed=True,
        hit_conservation_validated=True,
        full_game_continued_after_starter_exit=True,
    )
    assert state.status == "BLOCKED"
    assert "CORRELATION_UNDEFINED" in state.reason
    assert state.evidence_accruing is False
