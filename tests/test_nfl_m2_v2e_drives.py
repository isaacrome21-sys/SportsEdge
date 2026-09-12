import pytest

from sportsedge.sports.nfl.m2_v2e_drives import build_v2e_drive_training_rows


def _schedule():
    return [{
        "game_id": "2024_01_A_B",
        "season": 2024,
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


def test_v2e_drive_extractor_rejects_market_data():
    schedule = _schedule()
    schedule[0]["spread_line"] = -3.0
    with pytest.raises(ValueError, match="NFL_V2E_DRIVE_MARKET_DATA_PROHIBITED"):
        build_v2e_drive_training_rows(schedule, [])


def test_v2e_drive_extractor_fails_closed_if_one_side_missing():
    pbp = [{"game_id": "2024_01_A_B", "posteam": "A", "drive": 1, "play_type": "punt"}]
    with pytest.raises(ValueError, match="NFL_V2E_DRIVE_SIDE_EVIDENCE_MISSING"):
        build_v2e_drive_training_rows(_schedule(), pbp)
