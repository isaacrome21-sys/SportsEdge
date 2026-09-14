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
        "lead_at_exit": 1.0,
        "lead_preserved_to_final": 1.0,
    }
    row.update(overrides)
    return row


def test_win_is_derived_from_five_ip_exit_lead_and_preservation() -> None:
    qualified = normalize_starter_path(_path())
    assert qualified["win_probability"] == 1.0

    short = normalize_starter_path(_path(outs=14.0))
    assert short["win_probability"] == 0.0

    no_exit_lead = normalize_starter_path(
        _path(lead_at_exit=0.0, lead_preserved_to_final=0.0)
    )
    assert no_exit_lead["win_probability"] == 0.0


def test_final_score_win_proxy_cannot_override_qualification() -> None:
    with pytest.raises(MlbPitcherAccountingError, match="WIN_MISMATCH"):
        normalize_starter_path(_path(outs=14.0, win_probability=1.0))


def test_starter_events_must_be_scoped_before_dk_scoring() -> None:
    with pytest.raises(MlbPitcherAccountingError, match="NOT_STARTER_SCOPED"):
        normalize_starter_path(_path(starter_scoped_events=0.0))


def test_full_game_dk_points_shortcut_is_forbidden_for_mlb_pitchers() -> None:
    with pytest.raises(ValueError, match="DK_POINTS_BYPASS_FORBIDDEN"):
        dk_scores_from_samples(_pitcher(), "MLB", ({"dk_points": 35.0} for _ in range(1000)))


def test_mean_pitcher_projection_requires_workload_and_win_components() -> None:
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

    projection = projection_from_stats(
        _pitcher(),
        "MLB",
        {
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
            "win_probability": 0.52,
        },
        source="TEST",
    )
    assert projection.mean > 0.0
