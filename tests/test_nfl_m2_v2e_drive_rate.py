from copy import deepcopy

import pytest

from sportsedge.sports.nfl.m2_v2e_drive_rate import (
    V2E_DRIVE_RATE_CONTRACT,
    V2E_DRIVE_RATE_FIELD,
    V2E_DRIVE_RATE_SCOPE,
    build_v2e_pit_drive_rate_by_game,
)


def _schedule():
    return [
        {
            "game_id": "2024_01_A_B",
            "season": 2024,
            "gameday": "2024-09-01",
            "home_team": "B",
            "away_team": "A",
        },
        {
            "game_id": "2024_02_A_B",
            "season": 2024,
            "gameday": "2024-09-08",
            "home_team": "B",
            "away_team": "A",
        },
        {
            "game_id": "2024_03_A_B",
            "season": 2024,
            "gameday": "2024-09-15",
            "home_team": "B",
            "away_team": "A",
        },
    ]


def _drive_rows():
    return [
        {
            "game_id": "2024_01_A_B",
            "home_team": "B",
            "away_team": "A",
            "home_drives": 8,
            "away_drives": 12,
            "team_alias_policy": "NFLVERSE_PBP_CURRENT_FRANCHISE_CODE_V1",
        },
        {
            "game_id": "2024_02_A_B",
            "home_team": "B",
            "away_team": "A",
            "home_drives": 9,
            "away_drives": 11,
            "team_alias_policy": "NFLVERSE_PBP_CURRENT_FRANCHISE_CODE_V1",
        },
        {
            "game_id": "2024_03_A_B",
            "home_team": "B",
            "away_team": "A",
            "home_drives": 10,
            "away_drives": 10,
            "team_alias_policy": "NFLVERSE_PBP_CURRENT_FRANCHISE_CODE_V1",
        },
    ]


def test_v2e_drive_rate_contract_is_explicit():
    assert V2E_DRIVE_RATE_FIELD == "pit_drive_rate_delta"
    assert V2E_DRIVE_RATE_CONTRACT == "NFL_V2E_PRIOR_GAME_DRIVE_RATE_DELTA_V1"
    assert V2E_DRIVE_RATE_SCOPE == "PRIOR_RETAINED_GAME_DATES_ONLY"


def test_v2e_drive_rate_uses_only_prior_dates_and_zero_history_is_neutral():
    features = build_v2e_pit_drive_rate_by_game(_schedule(), _drive_rows())
    assert features["2024_01_A_B"] == {"home": 0.0, "away": 0.0}
    # After game 1, league team-drive mean is 10. B is 8 and A is 12.
    assert features["2024_02_A_B"]["home"] == pytest.approx(-2.0)
    assert features["2024_02_A_B"]["away"] == pytest.approx(2.0)


def test_v2e_drive_rate_excludes_current_game_but_future_state_can_change():
    baseline = build_v2e_pit_drive_rate_by_game(_schedule(), _drive_rows())
    mutated_rows = deepcopy(_drive_rows())
    mutated_rows[1]["home_drives"] = 1
    mutated_rows[1]["away_drives"] = 30
    mutated = build_v2e_pit_drive_rate_by_game(_schedule(), mutated_rows)

    # Game 2 cannot see its own realized drives.
    assert mutated["2024_02_A_B"] == baseline["2024_02_A_B"]
    # Game 3 may use game 2 because it is on a later date.
    assert mutated["2024_03_A_B"] != baseline["2024_03_A_B"]


def test_v2e_drive_rate_defers_all_same_day_updates():
    schedule = [
        {
            "game_id": "2024_01_A_B",
            "gameday": "2024-09-01",
            "home_team": "B",
            "away_team": "A",
        },
        {
            "game_id": "2024_01_C_D",
            "gameday": "2024-09-01",
            "home_team": "D",
            "away_team": "C",
        },
    ]
    drives = [
        {
            "game_id": "2024_01_A_B",
            "home_team": "B",
            "away_team": "A",
            "home_drives": 2,
            "away_drives": 20,
            "team_alias_policy": "NFLVERSE_PBP_CURRENT_FRANCHISE_CODE_V1",
        },
        {
            "game_id": "2024_01_C_D",
            "home_team": "D",
            "away_team": "C",
            "home_drives": 18,
            "away_drives": 4,
            "team_alias_policy": "NFLVERSE_PBP_CURRENT_FRANCHISE_CODE_V1",
        },
    ]
    features = build_v2e_pit_drive_rate_by_game(schedule, drives)
    assert features["2024_01_A_B"] == {"home": 0.0, "away": 0.0}
    assert features["2024_01_C_D"] == {"home": 0.0, "away": 0.0}


def test_v2e_drive_rate_carries_source_proven_franchise_alias_history():
    schedule = [
        {
            "game_id": "2016_01_OAK_NO",
            "gameday": "2016-09-11",
            "home_team": "NO",
            "away_team": "OAK",
        },
        {
            "game_id": "2020_01_LV_CAR",
            "gameday": "2020-09-13",
            "home_team": "CAR",
            "away_team": "LV",
        },
    ]
    drives = [
        {
            "game_id": "2016_01_OAK_NO",
            "home_team": "NO",
            "away_team": "OAK",
            "home_drives": 8,
            "away_drives": 12,
            "team_alias_policy": "NFLVERSE_PBP_CURRENT_FRANCHISE_CODE_V1",
        },
        {
            "game_id": "2020_01_LV_CAR",
            "home_team": "CAR",
            "away_team": "LV",
            "home_drives": 10,
            "away_drives": 10,
            "team_alias_policy": "NFLVERSE_PBP_CURRENT_FRANCHISE_CODE_V1",
        },
    ]
    features = build_v2e_pit_drive_rate_by_game(schedule, drives)
    # Prior league mean = 10; OAK's 12 carries forward to LV under frozen alias.
    assert features["2020_01_LV_CAR"]["away"] == pytest.approx(2.0)
    # CAR has no prior retained evidence and therefore inherits league mean.
    assert features["2020_01_LV_CAR"]["home"] == pytest.approx(0.0)


def test_v2e_drive_rate_fails_closed_on_cohort_mismatch():
    with pytest.raises(ValueError, match="NFL_V2E_DRIVE_RATE_COHORT_MISMATCH"):
        build_v2e_pit_drive_rate_by_game(_schedule(), _drive_rows()[:-1])
