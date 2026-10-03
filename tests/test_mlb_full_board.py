from __future__ import annotations

from sportsedge.mlb_full_board import SIDE_MARKETS, TOTAL_MARKETS, build_mlb_full_board, catalog_markets, family_for


def test_full_board_covers_every_catalog_side_total_and_prop():
    catalog = catalog_markets()
    board = build_mlb_full_board(
        [
            {"market": "MONEYLINE", "game_id": "1", "side": "HOME", "model_p": 0.58, "bet_status": "BLOCKED"},
            {"market": "TOTALS", "game_id": "1", "side": "OVER", "line": 8.5, "research_p": 0.54},
            {"market": "TEAM_TOTALS", "game_id": "1", "team_side": "HOME", "side": "OVER", "line": 4.5, "model_p": 0.51},
            {"engine_market": "HITS", "entity_id": "batter", "side": "OVER", "line": 1.5, "model_p": 0.57},
            {"market": "PITCHER_K", "entity_id": "pitcher", "side": "UNDER", "line": 5.5, "model_p": 0.51},
            {"market": "UNKNOWN"},
        ],
    )
    markets = {row["market"] for row in board["rows"]}
    assert markets == set(catalog)
    assert len(catalog) >= 38
    assert board["summary"]["catalog_markets"] == len(catalog)
    assert board["summary"]["official_bets"] == 0
    assert board["official_authority"] is False
    assert board["model_p_authority"] is False
    assert board["summary"]["side_rows"] >= len(SIDE_MARKETS)
    assert board["summary"]["total_rows"] >= len(TOTAL_MARKETS)
    assert board["summary"]["prop_rows"] >= 2
    assert {family_for(market) for market in SIDE_MARKETS} == {"SIDE"}
    assert {family_for(market) for market in TOTAL_MARKETS} == {"TOTAL"}
    blocked = [row for row in board["rows"] if row["market"] == "RUN_LINE"][0]
    assert blocked["presentation"] == "BLOCKED"
    assert blocked["reason"] == "NO_QUOTE_OR_ENGINE_ROW"
    moneyline = [row for row in board["rows"] if row["market"] == "MONEYLINE"][0]
    assert moneyline["presentation"] == "BLOCKED"
    assert moneyline["model_p"] == 0.58
    assert all(row["official_eligible"] is False for row in board["rows"])
    assert all(row["lane"] in {"SIDE", "TOTAL", "PROP"} for row in board["rows"])
    assert "UNKNOWN" not in markets
