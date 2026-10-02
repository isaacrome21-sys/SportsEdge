from __future__ import annotations

from sportsedge.mlb_full_board import SIDE_MARKETS, TOTAL_MARKETS, build_mlb_full_board


def test_full_board_keeps_sides_totals_and_props_and_missing_families():
    catalog = (
        "MONEYLINE", "RUN_LINE", "TOTALS", "TEAM_TOTALS",
        "HITS", "PITCHER_K", "FIRST_HOME_RUN",
    )
    board = build_mlb_full_board(
        [
            {"market": "MONEYLINE", "game_id": "1", "side": "HOME", "model_p": 0.58, "bet_status": "BLOCKED"},
            {"market": "TOTALS", "game_id": "1", "side": "OVER", "line": 8.5, "research_p": 0.54},
            {"engine_market": "HITS", "entity_id": "batter", "side": "OVER", "line": 1.5, "model_p": 0.57},
            {"market": "PITCHER_K", "entity_id": "pitcher", "side": "UNDER", "line": 5.5, "model_p": 0.51},
        ],
        catalog=catalog,
    )
    markets = {row["market"] for row in board["rows"]}
    assert markets == set(catalog)
    assert board["summary"]["official_bets"] == 0
    assert board["official_authority"] is False
    assert board["summary"]["side_rows"] >= 1
    assert board["summary"]["total_rows"] >= 1
    assert board["summary"]["prop_rows"] >= 2
    blocked = [row for row in board["rows"] if row["market"] == "RUN_LINE"][0]
    assert blocked["presentation"] == "BLOCKED"
    assert blocked["reason"] == "NO_QUOTE_OR_ENGINE_ROW"
    assert all(row["official_eligible"] is False for row in board["rows"])
    assert SIDE_MARKETS
    assert TOTAL_MARKETS
