from __future__ import annotations

from sportsedge.football_full_board import emit_all_props_side_totals as emit_football
from sportsedge.football_full_board import surface_markets
from sportsedge.mlb_full_board import catalog_markets, emit_all_props_side_totals, pair_sides


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
    moneyline = [row for row in board["rows"] if row["market"] == "MONEYLINE"]
    assert {row["side"] for row in moneyline} == {"HOME", "AWAY"}
    assert board["summary"]["both_sides"] is True
    assert board["summary"]["prop_rows"] >= 40
    assert board["summary"]["side_rows"] >= 8
    assert board["summary"]["total_rows"] >= 12
    assert board["official_authority"] is False
    assert all(row["official_eligible"] is False for row in board["rows"])
    assert all(set(pair_sides(market)) <= {row["side"] for row in board["rows"] if row["market"] == market} for market in catalog_markets())


def test_football_emits_both_sides_of_props_sides_and_totals():
    board = emit_football(
        sport="NFL",
        game_rows=[
            {"market": "moneyline", "game_id": "g", "side": "HOME", "model_p": 0.57, "american_odds": -130, "opposite_odds": 110},
            {"market": "total", "game_id": "g", "side": "OVER", "line": 47.5, "model_p": 0.52, "american_odds": -110, "opposite_odds": -110},
            {"market": "team_total", "game_id": "g", "team_side": "HOME", "side": "OVER", "line": 24.5, "model_p": 0.49},
        ],
        prop_rows=[
            {"provider_market": "player_pass_yds", "entity_id": "qb", "side": "OVER", "line": 245.5, "model_p": 0.55, "american_odds": -115, "opposite_odds": -105},
        ],
    )
    surface = {row["market"] for row in surface_markets()}
    assert surface <= {row["market"] for row in board["rows"]}
    moneyline = [row for row in board["rows"] if row["market"] == "moneyline"]
    assert {row["selection"] for row in moneyline} == {"HOME", "AWAY"}
    totals = [row for row in board["rows"] if row["market"] == "total"]
    assert {row["selection"] for row in totals} == {"OVER", "UNDER"}
    props = [row for row in board["rows"] if row["market"] == "passing_yards"]
    assert {row["selection"] for row in props} == {"OVER", "UNDER"}
    assert board["summary"]["prop_rows"] >= 2
    assert board["summary"]["side_rows"] >= 2
    assert board["summary"]["total_rows"] >= 2
    assert board["summary"]["both_sides"] is True
    assert board["official_authority"] is False
    assert board["prop_engine_state"] == "NO_ENGINE"
    assert all(row["official_eligible"] is False for row in board["rows"])

def test_mlb_prices_push_free_complement_only_when_opposite_quote_exists():
    board = emit_all_props_side_totals([
        {"market": "HITS", "entity_id": "batter", "side": "OVER", "line": 1.5, "model_p": 0.57, "american_odds": -110, "opposite_odds": -110},
        {"market": "TOTAL_BASES", "entity_id": "batter", "side": "OVER", "line": 1.5, "model_p": 0.48, "american_odds": 120},
        {"market": "RBI", "entity_id": "batter", "side": "OVER", "line": 1.0, "model_p": 0.42, "american_odds": 150, "opposite_odds": -180},
    ])
    hits = {row["side"]: row for row in board["rows"] if row["market"] == "HITS" and row["entity_id"] == "batter"}
    assert hits["UNDER"]["model_p"] == 0.43
    assert hits["UNDER"]["american_odds"] == -110
    assert hits["UNDER"]["reason"] == "COMPLEMENT_PRICED_FROM_QUOTED_SIDE"
    assert hits["UNDER"]["official_eligible"] is False
    bases = {row["side"]: row for row in board["rows"] if row["market"] == "TOTAL_BASES" and row["entity_id"] == "batter"}
    assert bases["UNDER"]["model_p"] is None
    assert bases["UNDER"]["reason"] == "COMPLEMENT_SIDE_NOT_QUOTED"
    rbi = {row["side"]: row for row in board["rows"] if row["market"] == "RBI" and row["entity_id"] == "batter"}
    assert rbi["UNDER"]["american_odds"] == -180
    assert rbi["UNDER"]["model_p"] is None
    assert rbi["UNDER"]["reason"] == "COMPLEMENT_PRICE_ONLY"


def test_football_prices_push_free_complement_and_nfl_report_attaches_board():
    board = emit_football(
        sport="NFL",
        game_rows=[
            {"market": "total", "game_id": "g", "side": "OVER", "line": 47.5, "model_p": 0.52, "american_odds": -110, "opposite_odds": -110},
        ],
        prop_rows=[
            {"provider_market": "player_pass_yds", "entity_id": "qb", "side": "OVER", "line": 245.5, "model_p": 0.55, "american_odds": -115, "opposite_odds": -105},
        ],
    )
    totals = {row["selection"]: row for row in board["rows"] if row["market"] == "total" and row["game_id"] == "g"}
    assert totals["UNDER"]["model_p"] == 0.48
    assert totals["UNDER"]["reason"] == "COMPLEMENT_PRICED_FROM_QUOTED_SIDE"
    props = {row["selection"]: row for row in board["rows"] if row["market"] == "passing_yards" and row["entity_id"] == "qb"}
    assert props["UNDER"]["model_p"] == 0.45
    assert props["UNDER"]["american_odds"] == -105
    from sportsedge.nfl_both_side_summary import attach_nfl_both_sides
    attached = attach_nfl_both_sides({"results": [], "summary": {"priced": 0}})
    assert attached["summary"]["both_sides"] is True
    assert attached["summary"]["prop_rows"] >= 2
    assert attached["summary"]["catalog_complete"] is True
