from sportsedge.football_full_board import emit_all_props_side_totals as emit_football
from sportsedge.mlb_full_board import catalog_markets, emit_all_props_side_totals


def test_mlb_emits_both_sides_of_props_sides_and_totals():
    board = emit_all_props_side_totals([
        {"market": "MONEYLINE", "game_id": "1", "side": "HOME", "model_p": 0.58, "american_odds": -120, "opposite_odds": 100},
        {"market": "TOTALS", "game_id": "1", "side": "OVER", "line": 8.5, "model_p": 0.54, "american_odds": -105},
        {"market": "HITS", "entity_id": "batter", "side": "OVER", "line": 1.5, "model_p": 0.57, "american_odds": -110, "opposite_odds": -110},
        {"market": "PITCHER_K", "entity_id": "pitcher", "side": "UNDER", "line": 5.5, "model_p": 0.51},
    ])
    markets = {row["market"] for row in board["rows"]}
    assert set(catalog_markets()) <= markets
    hits = [row for row in board["rows"] if row["market"] == "HITS"]
    assert {row["side"] for row in hits} == {"OVER", "UNDER"}
    totals = [row for row in board["rows"] if row["market"] == "TOTALS"]
    assert {row["side"] for row in totals} == {"OVER", "UNDER"}
    assert board["summary"]["both_sides"] is True
    assert board["summary"]["prop_rows"] >= 40
    assert board["summary"]["side_rows"] >= 8
    assert board["summary"]["total_rows"] >= 12
    assert board["official_authority"] is False
    assert all(row["official_eligible"] is False for row in board["rows"])


def test_football_emits_both_sides_of_props_sides_and_totals():
    board = emit_football(
        sport="NFL",
        game_rows=[
            {"market": "MONEYLINE", "game_id": "g", "side": "HOME", "model_p": 0.57, "american_odds": -130, "opposite_odds": 110},
            {"market": "TOTAL", "game_id": "g", "side": "OVER", "line": 47.5, "model_p": 0.52, "american_odds": -110, "opposite_odds": -110},
            {"market": "TEAM_TOTAL", "game_id": "g", "team_side": "HOME", "side": "OVER", "line": 24.5, "model_p": 0.49},
        ],
        prop_rows=[
            {"provider_market": "player_pass_yds", "entity_id": "qb", "side": "OVER", "line": 245.5, "model_p": 0.55, "american_odds": -115, "opposite_odds": -105},
        ],
    )
    moneyline = [row for row in board["rows"] if row["market"] == "moneyline"]
    assert {row["selection"] for row in moneyline} == {"HOME", "AWAY"}
    totals = [row for row in board["rows"] if row["market"] == "total"]
    assert {row["selection"] for row in totals} == {"OVER", "UNDER"}
    assert board["summary"]["prop_rows"] >= 2
    assert board["summary"]["side_rows"] >= 2
    assert board["summary"]["total_rows"] >= 2
    assert board["official_authority"] is False
    assert all(row["official_eligible"] is False for row in board["rows"])
