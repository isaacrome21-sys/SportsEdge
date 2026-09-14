from __future__ import annotations

import pytest

from sportsedge.dfs.mlb_pitcher_contract import (
    MlbPitcherAccountingError,
    normalize_starter_path,
)
from sportsedge.dfs.scoring import dk_scores_from_samples, projection_from_stats
from sportsedge.dfs.types import DKPlayer


def _pitcher() -> DKPlayer:
    return DKPlayer(
        player_id="sp1",
        name="Starter One",
        team="CHC",
        opponent="STL",
        positions=("P",),
        salary=9500,
    )


def _path(**overrides: float) -> dict[str, float]:
    row = {
        "outs": 18.0,
        "strikeouts": 7.0,
        "earned_runs": 2.0,
        "hits_allowed": 5.0,
        "walks_allowed": 2.0,
        "hbp_allowed": 0.0,
        "starter_exit_batters_faced": 25.0,
        "starter_exit_pitch_count": 94.0,
        "starter_scoped_events": 1.0,
        "hook_endogenous_to_path": 1.0,
        "hook_decision_batter_by_batter": 1.0,
        "hook_conditioned_on_pitch_count": 1.0,
        "hook_conditioned_on_runs_allowed": 1.0,
        "bullpen_remainder_routed": 1.0,
        "bullpen_hits_allowed": 3.0,
        "opponent_team_hits": 8.0,
        "game_simulated_to_final": 1.0,
        "lead_at_exit": 1.0,
        "lead_preserved_to_final": 1.0,
    }
    row.update(overrides)
    return row


def _expectation(**overrides: float) -> dict[str, float]:
    row = {
        "outs": 18.0,
        "strikeouts": 7.0,
        "earned_runs": 2.0,
        "hits_allowed": 5.0,
        "walks_allowed": 2.0,
        "expected_batters_faced": 25.0,
        "expected_pitch_count": 94.0,
        "p_reach_5ip": 0.82,
        "p_lead_at_exit": 0.62,
        "p_lead_preserved_to_final": 0.58,
        "hook_endogenous_to_path": 1.0,
        "hook_decision_batter_by_batter": 1.0,
        "hook_conditioned_on_pitch_count": 1.0,
        "hook_conditioned_on_runs_allowed": 1.0,
        "bullpen_remainder_routed": 1.0,
        "hit_conservation_validated": 1.0,
        "game_simulated_to_final": 1.0,
        "win_probability": 0.52,
    }
    row.update(overrides)
    return row


def test_win_is_derived_from_five_ip_exit_lead_and_final_game_resolution() -> None:
    qualified = normalize_starter_path(_path())
    assert qualified["win_probability"] == 1.0

    short = normalize_starter_path(_path(outs=14.0))
    assert short["win_probability"] == 0.0

    no_exit_lead = normalize_starter_path(_path(lead_at_exit=0.0, lead_preserved_to_final=0.0))
    assert no_exit_lead["win_probability"] == 0.0

    with pytest.raises(MlbPitcherAccountingError, match="GAME_NOT_SIMULATED_TO_FINAL"):
        normalize_starter_path(_path(game_simulated_to_final=0.0))


def test_final_score_win_proxy_cannot_override_qualification() -> None:
    with pytest.raises(MlbPitcherAccountingError, match="WIN_MISMATCH"):
        normalize_starter_path(_path(outs=14.0, win_probability=1.0))


def test_hook_must_be_endogenous_batter_by_batter_and_conditioned_on_path_state() -> None:
    with pytest.raises(MlbPitcherAccountingError, match="HOOK_NOT_ENDOGENOUS"):
        normalize_starter_path(_path(hook_endogenous_to_path=0.0))
    with pytest.raises(MlbPitcherAccountingError, match="HOOK_NOT_BATTER_BY_BATTER"):
        normalize_starter_path(_path(hook_decision_batter_by_batter=0.0))
    with pytest.raises(MlbPitcherAccountingError, match="HOOK_MISSING_PATH_PERFORMANCE_STATE"):
        normalize_starter_path(_path(hook_conditioned_on_runs_allowed=0.0))


def test_bullpen_receives_remainder_and_team_hits_are_conserved() -> None:
    with pytest.raises(MlbPitcherAccountingError, match="BULLPEN_REMAINDER_NOT_ROUTED"):
        normalize_starter_path(_path(bullpen_remainder_routed=0.0))
    with pytest.raises(MlbPitcherAccountingError, match="HIT_CONSERVATION_FAILED"):
        normalize_starter_path(_path(bullpen_hits_allowed=2.0, opponent_team_hits=8.0))
    valid = normalize_starter_path(_path(bullpen_hits_allowed=3.0, opponent_team_hits=8.0))
    assert valid["hits_allowed"] + valid["bullpen_hits_allowed"] == valid["opponent_team_hits"]


def test_starter_events_must_be_scoped_before_dk_scoring() -> None:
    with pytest.raises(MlbPitcherAccountingError, match="NOT_STARTER_SCOPED"):
        normalize_starter_path(_path(starter_scoped_events=0.0))


def test_full_game_dk_points_shortcut_is_forbidden_for_mlb_pitchers() -> None:
    with pytest.raises(ValueError, match="DK_POINTS_BYPASS_FORBIDDEN"):
        dk_scores_from_samples(_pitcher(), "MLB", ({"dk_points": 35.0} for _ in range(1000)))


def test_mean_pitcher_projection_requires_validated_path_accounting() -> None:
    with pytest.raises(MlbPitcherAccountingError, match="EXPECTATION_ACCOUNTING_MISSING"):
        projection_from_stats(
            _pitcher(),
            "MLB",
            {
                "outs": 18.0,
                "strikeouts": 7.0,
                "earned_runs": 2.0,
                "hits_allowed": 5.0,
                "walks_allowed": 2.0,
                "win_probability": 0.55,
            },
            source="TEST",
        )

    with pytest.raises(MlbPitcherAccountingError, match="PATH_ACCOUNTING_INVALID"):
        projection_from_stats(
            _pitcher(),
            "MLB",
            _expectation(hit_conservation_validated=0.0),
            source="TEST",
        )

    projection = projection_from_stats(
        _pitcher(),
        "MLB",
        _expectation(),
        source="TEST",
    )
    assert projection.mean > 0.0
