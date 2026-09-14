from __future__ import annotations

import pytest

from sportsedge.dfs.mlb_pitcher_pathset import (
    MlbPitcherPathSetError,
    MlbPitcherPathSetPolicy,
    validate_mlb_pitcher_path_set,
)


def _policy(**overrides: object) -> MlbPitcherPathSetPolicy:
    values = {
        "policy_id": "TEST_FROZEN_PATH_SET_V1",
        "status": "FROZEN",
        "min_paths": 8,
        "p_outs_ge_21_min": 0.25,
        "p_outs_ge_21_max": 0.75,
        "min_bullpen_active_fraction": 0.50,
        "min_lead_divergence_fraction": 0.10,
    }
    values.update(overrides)
    return MlbPitcherPathSetPolicy(**values)


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


def test_valid_mixed_path_set_passes_computed_checks() -> None:
    result = validate_mlb_pitcher_path_set(_valid_rows(), _policy())
    assert result.passed is True
    assert result.bf_earned_run_correlation < 0.0
    assert result.p_outs_ge_21 == 0.5
    assert result.bullpen_active_fraction == 0.75
    assert result.lead_divergence_fraction == 0.125
    assert len(result.path_set_sha256) == 64
    assert len(result.policy_sha256) == 64


def test_all_complete_game_self_assertion_shape_fails_without_trusting_flags() -> None:
    rows = [
        {
            "starter_exit_batters_faced": 38.0,
            "earned_runs": float(i % 5),
            "outs": 27.0,
            "bullpen_hits_allowed": 0.0,
            "lead_at_exit": 1.0,
            "lead_preserved_to_final": 1.0,
            "hook_endogenous_to_path": 1.0,
            "hook_decision_batter_by_batter": 1.0,
            "bullpen_remainder_routed": 1.0,
            "game_simulated_to_final": 1.0,
        }
        for i in range(8)
    ]
    with pytest.raises(MlbPitcherPathSetError, match="CORRELATION_UNDEFINED"):
        validate_mlb_pitcher_path_set(rows, _policy())


def test_nonnegative_bf_er_relationship_fails() -> None:
    rows = _valid_rows()
    for i, row in enumerate(rows):
        row["starter_exit_batters_faced"] = float(25 + i)
    result = validate_mlb_pitcher_path_set(rows, _policy())
    assert result.passed is False
    assert "BF_EARNED_RUN_CORRELATION_NOT_NEGATIVE" in result.failures


def test_outs_tail_outside_frozen_band_fails() -> None:
    rows = _valid_rows()
    for row in rows:
        row["outs"] = 27.0
    result = validate_mlb_pitcher_path_set(rows, _policy())
    assert result.passed is False
    assert "OUTS_GE_21_OUTSIDE_FROZEN_BAND" in result.failures


def test_bullpen_never_absorbs_offense_fails() -> None:
    rows = _valid_rows()
    for row in rows:
        row["bullpen_hits_allowed"] = 0.0
    result = validate_mlb_pitcher_path_set(rows, _policy())
    assert result.passed is False
    assert "BULLPEN_ACTIVE_FRACTION_TOO_LOW" in result.failures


def test_lead_never_changes_after_exit_fails() -> None:
    rows = _valid_rows()
    for row in rows:
        row["lead_preserved_to_final"] = row["lead_at_exit"]
    result = validate_mlb_pitcher_path_set(rows, _policy())
    assert result.passed is False
    assert "LEAD_FINAL_DIVERGENCE_TOO_LOW" in result.failures


def test_single_complete_game_is_legal_inside_valid_distribution() -> None:
    rows = _valid_rows()
    rows[0].update(
        {
            "starter_exit_batters_faced": 38.0,
            "earned_runs": 0.0,
            "outs": 27.0,
            "bullpen_hits_allowed": 0.0,
        }
    )
    result = validate_mlb_pitcher_path_set(rows, _policy())
    assert result.passed is True


def test_unfrozen_policy_cannot_validate_paths() -> None:
    with pytest.raises(MlbPitcherPathSetError, match="POLICY_NOT_FROZEN"):
        validate_mlb_pitcher_path_set(_valid_rows(), _policy(status="PROPOSED"))
