import pytest

from scripts.run_nfl_v2e_candidate_validation import _identity_schedule
from sportsedge.sports.nfl.m2_v2e_drives import (
    V2E_TEAM_ALIAS_POLICY,
    build_v2e_drive_training_rows,
)


def _schedule():
    return [{
        "game_id": "2024_01_A_B",
        "season": 2024,
        "game_type": "REG",
        "home_team": "B",
        "away_team": "A",
    }]


def test_v2e_drive_extractor_separates_offense_defense_and_safety_scoring():
    pbp = [
        # Away offensive touchdown + good PAT on drive 1.
        {"game_id": "2024_01_A_B", "posteam": "A", "drive": 1, "touchdown": 1, "td_team": "A"},
        {"game_id": "2024_01_A_B", "posteam": "A", "drive": 1, "extra_point_result": "good"},
        # Home pick-six allowed: touchdown belongs to A while B possessed ball.
        {"game_id": "2024_01_A_B", "posteam": "B", "drive": 2, "touchdown": 1, "td_team": "A"},
        # Away safety allowed.
        {"game_id": "2024_01_A_B", "posteam": "A", "drive": 3, "safety": 1},
        # Home made field goal.
        {"game_id": "2024_01_A_B", "posteam": "B", "drive": 4, "field_goal_result": "made"},
        # One empty/no-score drive for each side.
        {"game_id": "2024_01_A_B", "posteam": "A", "drive": 5, "play_type": "punt"},
        {"game_id": "2024_01_A_B", "posteam": "B", "drive": 6, "play_type": "punt"},
    ]
    rows = build_v2e_drive_training_rows(_schedule(), pbp)
    assert len(rows) == 1
    row = rows[0]
    assert row["away_drives"] == 3
    assert row["away_td_xp"] == 1
    assert row["away_safety_allowed"] == 1
    assert row["away_no_score"] == 1
    assert row["home_drives"] == 3
    assert row["home_def_td_7_allowed"] == 1
    assert row["home_fg"] == 1
    assert row["home_no_score"] == 1
    assert row["team_alias_policy"] == V2E_TEAM_ALIAS_POLICY
    assert row["team_alias_application_count"] == 0


def test_v2e_drive_extractor_rejects_market_data():
    schedule = _schedule()
    schedule[0]["spread_line"] = -3.0
    with pytest.raises(ValueError, match="NFL_V2E_DRIVE_MARKET_DATA_PROHIBITED"):
        build_v2e_drive_training_rows(schedule, [])


def test_v2e_drive_extractor_fails_closed_if_one_side_missing():
    pbp = [{"game_id": "2024_01_A_B", "posteam": "A", "drive": 1, "play_type": "punt"}]
    with pytest.raises(ValueError, match="NFL_V2E_DRIVE_SIDE_EVIDENCE_MISSING"):
        build_v2e_drive_training_rows(_schedule(), pbp)


def test_v2e_identity_schedule_only_requires_retained_history_games():
    schedule = _schedule() + [{
        "game_id": "2024_01_C_D",
        "season": 2024,
        "game_type": "REG",
        "home_team": "D",
        "away_team": "C",
    }]
    retained = _identity_schedule(schedule, allowed_game_ids={"2024_01_A_B"})
    assert [row["game_id"] for row in retained] == ["2024_01_A_B"]


def test_v2e_identity_schedule_fails_if_retained_game_is_not_in_schedule():
    with pytest.raises(SystemExit, match="NFL_M2_V2E_RETAINED_SCHEDULE_IDENTITY_MISSING"):
        _identity_schedule(_schedule(), allowed_game_ids={"2024_01_A_B", "2024_01_X_Y"})


def test_v2e_drive_extractor_applies_only_source_proven_oak_to_lv_alias():
    schedule = [{
        "game_id": "2016_01_OAK_NO",
        "season": 2016,
        "game_type": "REG",
        "home_team": "NO",
        "away_team": "OAK",
    }]
    pbp = [
        {"game_id": "2016_01_OAK_NO", "posteam": "LV", "drive": 1, "play_type": "punt"},
        {"game_id": "2016_01_OAK_NO", "posteam": "NO", "drive": 2, "play_type": "punt"},
    ]
    row = build_v2e_drive_training_rows(schedule, pbp)[0]
    assert row["away_team"] == "OAK"
    assert row["away_drives"] == 1
    assert row["home_drives"] == 1
    assert row["team_alias_policy"] == "NFLVERSE_PBP_CURRENT_FRANCHISE_CODE_V1"
    assert row["team_alias_application_count"] == 1


def test_v2e_drive_extractor_applies_only_source_proven_sd_to_lac_alias():
    schedule = [{
        "game_id": "2016_01_KC_SD",
        "season": 2016,
        "game_type": "REG",
        "home_team": "SD",
        "away_team": "KC",
    }]
    pbp = [
        {"game_id": "2016_01_KC_SD", "posteam": "LAC", "drive": 1, "play_type": "punt"},
        {"game_id": "2016_01_KC_SD", "posteam": "KC", "drive": 2, "play_type": "punt"},
    ]
    row = build_v2e_drive_training_rows(schedule, pbp)[0]
    assert row["home_team"] == "SD"
    assert row["home_drives"] == 1
    assert row["away_drives"] == 1
    assert row["team_alias_application_count"] == 1


def test_v2e_drive_extractor_does_not_rewrite_modern_lv_identity():
    schedule = [{
        "game_id": "2024_01_LV_LAC",
        "season": 2024,
        "game_type": "REG",
        "home_team": "LAC",
        "away_team": "LV",
    }]
    pbp = [
        {"game_id": "2024_01_LV_LAC", "posteam": "LV", "drive": 1, "play_type": "punt"},
        {"game_id": "2024_01_LV_LAC", "posteam": "LAC", "drive": 2, "play_type": "punt"},
    ]
    row = build_v2e_drive_training_rows(schedule, pbp)[0]
    assert row["away_team"] == "LV"
    assert row["home_team"] == "LAC"
    assert row["team_alias_application_count"] == 0


def test_v2e_drive_extractor_never_fuzzy_maps_unknown_team_code():
    schedule = [{
        "game_id": "2016_01_OAK_NO",
        "season": 2016,
        "game_type": "REG",
        "home_team": "NO",
        "away_team": "OAK",
    }]
    pbp = [
        {"game_id": "2016_01_OAK_NO", "posteam": "LAS", "drive": 1, "play_type": "punt"},
        {"game_id": "2016_01_OAK_NO", "posteam": "NO", "drive": 2, "play_type": "punt"},
    ]
    with pytest.raises(ValueError, match="NFL_V2E_DRIVE_SIDE_EVIDENCE_MISSING"):
        build_v2e_drive_training_rows(schedule, pbp)
