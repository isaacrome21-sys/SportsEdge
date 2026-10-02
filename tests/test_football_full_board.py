from __future__ import annotations

from sportsedge.football_full_board import build_football_full_board


def test_nfl_board_keeps_sides_totals_props_and_prices_team_total_derivative():
    board = build_football_full_board(
        sport="NFL",
        game_rows=[
            {"market": "MONEYLINE", "game_id": "g1", "side": "HOME", "model_p": 0.61, "reason": "BLOCKED"},
            {"market": "SPREAD", "game_id": "g1", "side": "HOME", "line": -3.5, "model_p": 0.54},
            {"market": "TOTAL", "game_id": "g1", "side": "OVER", "line": 47.5, "model_p": 0.52},
        ],
        prop_rows=[
            {"provider_market": "player_pass_yds", "player_name": "QB", "side": "OVER", "line": 245.5, "model_p": 0.56},
        ],
        team_total_requests=[
            {"game_id": "g1", "team_side": "HOME", "line": 24.5, "quoted_side": "OVER"},
            {"game_id": "g1", "team_side": "AWAY", "line": 21.5, "quoted_side": "UNDER"},
        ],
        distribution=[{"home_score": 28, "away_score": 17}, {"home_score": 20, "away_score": 24}],
    )
    assert board["official_authority"] is False
    assert board["prop_engine_state"] == "NO_ENGINE"
    assert board["summary"]["official_bets"] == 0
    assert board["summary"]["side_rows"] == 2
    assert board["summary"]["total_rows"] == 3
    assert board["summary"]["prop_rows"] > 1
    team_totals = [row for row in board["rows"] if row["market"] == "TEAM_TOTAL" and row["model_p"] is not None]
    assert len(team_totals) == 2
    assert all(row["official_eligible"] is False for row in board["rows"])
    missing = [row for row in board["rows"] if row["market"] == "player_rush_yds"][0]
    assert missing["presentation"] == "BLOCKED"


def test_team_total_without_distribution_stays_no_model():
    board = build_football_full_board(
        sport="CFB",
        game_rows=[{"market": "MONEYLINE", "model_p": 0.5, "game_id": "g"}],
        team_total_requests=[{"game_id": "g", "team_side": "HOME", "line": 27.5}],
    )
    row = [item for item in board["rows"] if item["market"] == "TEAM_TOTAL"][0]
    assert row["presentation"] == "NO_MODEL"
    assert row["reason"] == "TEAM_TOTAL_DISTRIBUTION_REQUIRED"
    assert board["summary"]["official_bets"] == 0
