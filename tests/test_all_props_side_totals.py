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


def test_mlb_prices_integer_complement_from_supplied_push_or_count_pmf():
    board = emit_all_props_side_totals([
        {"market": "RBI", "entity_id": "batter", "side": "OVER", "line": 1.0, "model_p": 0.42, "american_odds": 150, "opposite_odds": -180, "push_p": 0.18},
        {"market": "HITS", "entity_id": "batter", "side": "OVER", "line": 1.0, "model_p": 0.30, "american_odds": -110, "opposite_odds": -110, "count_pmf": [0.20, 0.50, 0.30]},
    ])
    rbi = {row["side"]: row for row in board["rows"] if row["market"] == "RBI" and row["entity_id"] == "batter"}
    assert rbi["UNDER"]["model_p"] == 0.40
    assert rbi["UNDER"]["reason"] == "COMPLEMENT_PRICED_FROM_QUOTED_SIDE"
    assert rbi["UNDER"]["official_eligible"] is False
    hits = {row["side"]: row for row in board["rows"] if row["market"] == "HITS" and row["entity_id"] == "batter"}
    assert hits["UNDER"]["model_p"] == 0.20
    assert hits["UNDER"]["reason"] == "COMPLEMENT_PRICED_FROM_QUOTED_SIDE"
    assert board["summary"]["priced_complement_rows"] >= 2


def test_mlb_run_result_keeps_opposite_quote_for_the_board():
    from dataclasses import asdict
    from sportsedge.mlb_run_machine import MLBMachineResult
    from sportsedge.mlb_full_board import build_mlb_full_board

    result = MLBMachineResult(
        source_index=0, game_id="1", market="TOTALS", entity_id="game", line=8.5, side="OVER",
        american_odds=-105, model_p=0.54, bet_status="BLOCKED", reason="RESEARCH_ROW",
        opposite_odds=-115,
    )
    board = build_mlb_full_board([asdict(result)])
    totals = {row["side"]: row for row in board["rows"] if row["market"] == "TOTALS" and row["game_id"] == "1"}
    assert totals["UNDER"]["american_odds"] == -115
    assert totals["UNDER"]["model_p"] == 0.46
    assert totals["UNDER"]["reason"] == "COMPLEMENT_PRICED_FROM_QUOTED_SIDE"


def test_football_emits_both_sides_of_remaining_prop_families():
    board = emit_football(sport="NFL")
    for market in ("receiving_tds", "rushing_tds", "rush_rec_tds", "solo_tackles", "tds_over"):
        sides = {row["selection"] for row in board["rows"] if row["market"] == market}
        assert sides == {"OVER", "UNDER"}, market
    quoted = emit_football(
        sport="CFB",
        prop_rows=[{
            "provider_market": "player_reception_tds",
            "entity_id": "wr",
            "side": "OVER",
            "line": 0.5,
            "model_p": 0.41,
            "american_odds": 120,
            "opposite_odds": -150,
        }],
    )
    props = {row["selection"]: row for row in quoted["rows"] if row["market"] == "receiving_tds" and row["entity_id"] == "wr"}
    assert props["UNDER"]["model_p"] == 0.59
    assert props["UNDER"]["american_odds"] == -150
    assert quoted["summary"]["both_sides"] is True
    assert quoted["official_authority"] is False


def test_nfl_auto_payload_attaches_board_without_editing_frozen_script():
    from pathlib import Path
    from sportsedge.nfl_both_side_summary import attach_nfl_auto_payload

    script = Path("scripts/run_nfl_auto.py").read_text(encoding="utf-8")
    assert "attach_nfl_both_sides" not in script
    assert "nfl_both_side_summary" not in script
    attached = attach_nfl_auto_payload({
        "schema_version": "NFL_AUTO_RUN_V2",
        "status": "BLOCKED",
        "report": {"results": [], "summary": {}},
    })
    assert attached["summary"]["both_sides"] is True
    assert attached["summary"]["catalog_complete"] is True
    assert attached["summary"]["prop_rows"] >= 2
    assert attached["report"]["summary"]["full_board"]["official_authority"] is False


def test_mlb_pairs_sibling_quote_without_timestamp():
    board = emit_all_props_side_totals([
        {"market": "HITS", "entity_id": "batter", "game_id": "1", "side": "OVER", "line": 1.5, "model_p": 0.57, "american_odds": -110},
        {"market": "HITS", "entity_id": "batter", "game_id": "1", "side": "UNDER", "line": 1.5, "model_p": 0.43, "american_odds": -110},
    ])
    hits = {row["side"]: row for row in board["rows"] if row["market"] == "HITS" and row["entity_id"] == "batter"}
    assert set(hits) >= {"OVER", "UNDER"}
    assert hits["OVER"]["model_p"] == 0.57
    assert hits["UNDER"]["model_p"] == 0.43
    assert hits["UNDER"]["official_eligible"] is False


def test_football_maps_remaining_prop_families_to_both_sides():
    board = emit_football(
        sport="NFL",
        prop_rows=[
            {"provider_market": "player_targets", "entity_id": "wr", "side": "OVER", "line": 6.5, "model_p": 0.52, "american_odds": -115, "opposite_odds": -105},
            {"provider_market": "player_first_td", "entity_id": "rb", "side": "OVER", "line": 0.5, "model_p": 0.22, "american_odds": 250, "opposite_odds": -320},
            {"provider_market": "team_sacks", "entity_id": "home", "side": "OVER", "line": 2.5, "model_p": 0.48, "american_odds": -110, "opposite_odds": -110},
        ],
    )
    targets = {row["selection"]: row for row in board["rows"] if row["market"] == "targets" and row["entity_id"] == "wr"}
    assert targets["UNDER"]["model_p"] == 0.48
    assert targets["UNDER"]["reason"] == "COMPLEMENT_PRICED_FROM_QUOTED_SIDE"
    first = {row["selection"] for row in board["rows"] if row["market"] == "first_td"}
    sacks = {row["selection"] for row in board["rows"] if row["market"] == "team_sacks"}
    assert first == {"OVER", "UNDER"}
    assert sacks == {"OVER", "UNDER"}
    assert board["summary"]["both_sides"] is True
    assert board["official_authority"] is False


def test_mlb_empty_board_lists_both_sides_of_every_catalog_market():
    from sportsedge.mlb_full_board import catalog_complete

    board = emit_all_props_side_totals([])
    assert catalog_complete(board["summary"]) is True
    assert board["summary"]["catalog_markets"] >= 38
    for market in catalog_markets():
        sides = {row["side"] for row in board["rows"] if row["market"] == market}
        assert set(pair_sides(market)) <= sides
        assert all(row["official_eligible"] is False for row in board["rows"] if row["market"] == market)


def test_mlb_phone_card_lists_catalog_when_engine_payload_has_no_board():
    from scripts.render_mlb_myspari_card import both_side_board_section

    text = both_side_board_section({"results": [
        {"market": "HITS", "entity_id": "batter", "side": "OVER", "line": 1.5, "model_p": 0.57, "american_odds": -110, "opposite_odds": -110},
    ]})
    assert "HITS" in text
    assert "UNDER" in text
    assert "Price needed" in text
    assert "OFFICIAL" not in text
    assert "Truth Gate" not in text
    assert "model_p" not in text
    assert "catalog_complete=True" in text or "both_sides=True" in text


def test_football_phone_card_lists_catalog_when_engine_payload_has_no_board():
    from scripts.render_football_board_card import render_markdown

    text = render_markdown({"sport": "NFL", "results": [
        {"market": "moneyline", "game_id": "g", "side": "HOME", "model_p": 0.57, "american_odds": -130, "opposite_odds": 110},
    ]})
    assert "passing_yards" in text
    assert "moneyline" in text
    assert "OFFICIAL" not in text
    assert "Truth Gate" not in text
    assert "model_p" not in text
    assert "Price needed" in text
