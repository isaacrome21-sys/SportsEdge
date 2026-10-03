from __future__ import annotations

from sportsedge.football_full_board import build_football_full_board, surface_markets


def test_nfl_board_covers_surface_sides_totals_props_and_prices_derivatives():
    board = build_football_full_board(
        sport="NFL",
        game_rows=[
            {"market": "moneyline", "game_id": "g1", "side": "HOME", "model_p": 0.61, "reason": "BLOCKED"},
            {"market": "spread", "game_id": "g1", "side": "HOME", "line": -3.5, "model_p": 0.54},
            {"market": "total", "game_id": "g1", "side": "OVER", "line": 47.5, "model_p": 0.52},
        ],
        prop_rows=[
            {"provider_market": "player_pass_yds", "player_name": "QB", "side": "OVER", "line": 245.5, "model_p": 0.56},
        ],
        team_total_requests=[
            {"game_id": "g1", "team_side": "HOME", "line": 24.5, "quoted_side": "OVER"},
            {"game_id": "g1", "team_side": "AWAY", "line": 21.5, "quoted_side": "UNDER"},
        ],
        period_requests=[
            {"market": "first_half_total", "game_id": "g1", "line": 24.5, "quoted_side": "OVER"},
            {"market": "quarter_moneyline", "game_id": "g1", "quarter": "q1", "quoted_side": "HOME"},
        ],
        distribution=[
            {
                "home_score": 28, "away_score": 17,
                "first_half_home_score": 14, "first_half_away_score": 10,
                "q1_home_score": 7, "q1_away_score": 3,
            },
            {
                "home_score": 20, "away_score": 24,
                "first_half_home_score": 10, "first_half_away_score": 17,
                "q1_home_score": 3, "q1_away_score": 7,
            },
        ],
    )
    surface = {row["market"] for row in surface_markets()}
    emitted = {row["market"] for row in board["rows"]}
    assert surface <= emitted
    assert len(surface) >= 51
    assert board["official_authority"] is False
    assert board["prop_engine_state"] == "NO_ENGINE"
    assert board["summary"]["official_bets"] == 0
    assert board["summary"]["side_rows"] >= 2
    assert board["summary"]["total_rows"] >= 3
    assert board["summary"]["prop_rows"] > 1
    assert board["summary"]["situational_rows"] >= 1
    team_totals = [row for row in board["rows"] if row["market"] == "team_total" and row["model_p"] is not None]
    assert len(team_totals) == 2
    half = [row for row in board["rows"] if row["market"] == "first_half_total" and row["model_p"] is not None][0]
    assert half["reason"] == "PERIOD_DERIVATIVE_NOT_PROMOTION"
    assert half["official_eligible"] is False
    missing = [row for row in board["rows"] if row["market"] == "rushing_yards"][0]
    assert missing["presentation"] == "BLOCKED"
    assert missing["engine_state"] == "NO_ENGINE"
    assert all(row["official_eligible"] is False for row in board["rows"])


def test_team_total_without_distribution_stays_no_model():
    board = build_football_full_board(
        sport="CFB",
        game_rows=[{"market": "moneyline", "model_p": 0.5, "game_id": "g"}],
        team_total_requests=[{"game_id": "g", "team_side": "HOME", "line": 27.5}],
    )
    row = [item for item in board["rows"] if item["market"] == "team_total"][0]
    assert row["presentation"] == "NO_MODEL"
    assert row["reason"] == "TEAM_TOTAL_DISTRIBUTION_REQUIRED"
    assert board["summary"]["official_bets"] == 0
    assert board["summary"]["surface_markets"] >= 51


def test_machine_results_cover_every_side_total_and_prop_without_authority():
    from types import SimpleNamespace

    from sportsedge.football_full_board import board_from_machine_results, surface_markets

    results = [
        SimpleNamespace(market="MONEYLINE", game_id="g1", side="HOME", line=None, american_odds=-120, model_p=0.57, reason="RESEARCH"),
        SimpleNamespace(market="SPREAD", game_id="g1", side="HOME", line=-3.5, american_odds=-110, model_p=0.52, reason="RESEARCH"),
        SimpleNamespace(market="TOTAL", game_id="g1", side="OVER", line=47.5, american_odds=-110, model_p=0.51, reason="RESEARCH"),
        SimpleNamespace(market="TEAM_TOTAL", game_id="g1", side="OVER", line=24.5, american_odds=-115, model_p=0.49, reason="RESEARCH"),
        SimpleNamespace(market="GAME", game_id="g1", side=None, line=None, american_odds=None, model_p=None, reason="GAME_OUTPUT_MISSING"),
        SimpleNamespace(market="PLAYER_PROPS", game_id=None, side=None, line=None, american_odds=None, model_p=None, reason="NFL_PROPS_NO_ENGINE"),
    ]
    board = board_from_machine_results("NFL", results)
    surface = {row["market"] for row in surface_markets()}
    assert surface <= {row["market"] for row in board["rows"]}
    assert board["summary"]["side_rows"] >= 2
    assert board["summary"]["total_rows"] >= 2
    assert board["summary"]["prop_rows"] > 1
    assert board["summary"]["both_sides"] is True
    assert board["official_authority"] is False
    assert board["prop_engine_state"] == "NO_ENGINE"
    assert all(row["official_eligible"] is False for row in board["rows"])
    priced = [row for row in board["rows"] if row["market"] == "moneyline"][0]
    assert priced["model_p"] == 0.57
    blocked = [row for row in board["rows"] if row["market"] == "rushing_yards"][0]
    assert blocked["presentation"] == "BLOCKED"
