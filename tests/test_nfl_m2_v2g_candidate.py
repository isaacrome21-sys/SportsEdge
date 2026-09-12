from __future__ import annotations

from copy import deepcopy

import pytest

from sportsedge.sports.nfl.m2_v2g_candidate import (
    NFL_M2_V2G_CANDIDATE_MODEL_ID,
    NFL_M2_V2G_EVENT_CONTRACT,
    build_nfl_v2g_game_event_rows,
    derive_nfl_m2_v2g_score_distribution,
    fit_nfl_m2_v2g_candidate,
)


def _training_rows():
    return [
        {
            "event_contract": NFL_M2_V2G_EVENT_CONTRACT,
            "game_id": "g1",
            "season": 2020,
            "home_team": "A",
            "away_team": "B",
            "home_drives": 10,
            "home_touchdowns": 3,
            "home_field_goals": 2,
            "home_other_no_score": 5,
            "away_drives": 10,
            "away_touchdowns": 2,
            "away_field_goals": 2,
            "away_other_no_score": 6,
        },
        {
            "event_contract": NFL_M2_V2G_EVENT_CONTRACT,
            "game_id": "g2",
            "season": 2020,
            "home_team": "B",
            "away_team": "A",
            "home_drives": 11,
            "home_touchdowns": 2,
            "home_field_goals": 3,
            "home_other_no_score": 6,
            "away_drives": 11,
            "away_touchdowns": 4,
            "away_field_goals": 1,
            "away_other_no_score": 6,
        },
    ]


def test_v2g_distribution_is_normalized_deterministic_and_football_native():
    model = fit_nfl_m2_v2g_candidate(_training_rows())
    assert model.model_id == NFL_M2_V2G_CANDIDATE_MODEL_ID

    prediction = {"home_team": "A", "away_team": "B"}
    first = derive_nfl_m2_v2g_score_distribution(model, prediction)
    second = derive_nfl_m2_v2g_score_distribution(model, prediction)

    assert first == second
    assert sum(row["weight"] for row in first) == pytest.approx(1.0, abs=1e-12)
    assert all(row["home_score"] >= 0 and row["away_score"] >= 0 for row in first)

    for row in first:
        for score in (row["home_score"], row["away_score"]):
            assert any(
                7 * touchdowns + 3 * field_goals == score
                for touchdowns in range(model.max_touchdowns + 1)
                for field_goals in range(model.max_field_goals + 1)
            )


def test_v2g_prediction_is_invariant_to_sportsbook_fields():
    model = fit_nfl_m2_v2g_candidate(_training_rows())
    clean = {"home_team": "A", "away_team": "B"}
    contaminated = {
        **clean,
        "spread_line": -99.5,
        "total_line": 999.5,
        "moneyline": -50000,
        "home_spread_odds": -10000,
        "away_spread_odds": 9000,
        "closing_spread": 41.5,
        "closing_total": 12.5,
    }
    assert derive_nfl_m2_v2g_score_distribution(model, clean) == derive_nfl_m2_v2g_score_distribution(model, contaminated)


def test_v2g_fit_is_invariant_to_market_fields_on_training_rows():
    clean = _training_rows()
    contaminated = deepcopy(clean)
    for index, row in enumerate(contaminated):
        row.update({
            "spread_line": 50.0 + index,
            "total_line": 500.0 + index,
            "home_spread_odds": -10000,
            "away_spread_odds": 9000,
        })
    clean_model = fit_nfl_m2_v2g_candidate(clean)
    contaminated_model = fit_nfl_m2_v2g_candidate(contaminated)
    assert clean_model == contaminated_model


def test_v2g_event_builder_marks_td_fg_and_other_without_score_inference():
    schedule = [{
        "game_id": "g1",
        "game_type": "REG",
        "season": 2020,
        "week": 1,
        "home_team": "A",
        "away_team": "B",
        "home_score": 17,
        "away_score": 10,
    }]
    pbp = [
        {"game_id": "g1", "posteam": "A", "drive": 1, "touchdown": 0, "play_type": "run"},
        {"game_id": "g1", "posteam": "A", "drive": 1, "touchdown": 1, "td_team": "A", "play_type": "pass"},
        {"game_id": "g1", "posteam": "A", "drive": 2, "touchdown": 0, "play_type": "field_goal", "field_goal_result": "made"},
        {"game_id": "g1", "posteam": "A", "drive": 3, "touchdown": 0, "play_type": "punt"},
        {"game_id": "g1", "posteam": "B", "drive": 1, "touchdown": 1, "td_team": "B", "play_type": "run"},
        {"game_id": "g1", "posteam": "B", "drive": 2, "touchdown": 0, "play_type": "punt"},
    ]
    rows = build_nfl_v2g_game_event_rows(schedule, pbp)
    assert len(rows) == 1
    row = rows[0]
    assert (row["home_drives"], row["home_touchdowns"], row["home_field_goals"], row["home_other_no_score"]) == (3, 1, 1, 1)
    assert (row["away_drives"], row["away_touchdowns"], row["away_field_goals"], row["away_other_no_score"]) == (2, 1, 0, 1)


def test_v2g_event_builder_fails_closed_without_drive_identity():
    schedule = [{"game_id": "g1", "game_type": "REG", "season": 2020, "home_team": "A", "away_team": "B"}]
    pbp = [{"game_id": "g1", "posteam": "A", "drive": "", "touchdown": 0, "play_type": "run"}]
    with pytest.raises(ValueError, match="NFL_M2_V2G_POSSESSION_IDENTITY_MISSING"):
        build_nfl_v2g_game_event_rows(schedule, pbp)


def test_v2g_training_counts_fail_closed():
    rows = _training_rows()
    rows[0]["home_other_no_score"] = 99
    with pytest.raises(ValueError, match="NFL_M2_V2G_EVENT_COUNT_INVALID"):
        fit_nfl_m2_v2g_candidate(rows)
