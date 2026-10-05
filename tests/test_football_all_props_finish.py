from __future__ import annotations

import json
from pathlib import Path

from sportsedge.football_full_board import catalog_complete, emit_all_props_side_totals
from scripts.render_football_board_card import render_markdown
from scripts.run_auto_nfl_resilient import build_card


def test_empty_nfl_card_still_lists_every_prop_side_and_total():
    card = build_card([])
    summary = card["summary"]
    assert summary["both_sides"] is True
    assert summary["catalog_complete"] is True
    assert catalog_complete(summary)
    assert summary["side_rows"] >= 16
    assert summary["total_rows"] >= 10
    assert summary["prop_rows"] >= 40
    assert card["odds_api_called"] is False
    assert card["governance"]["official_authority"] is False
    assert card["full_board"]["prop_engine_state"] == "NO_ENGINE"
    markets = {row["market"] for row in card["full_board"]["rows"]}
    assert {"moneyline", "spread", "total", "passing_yards", "receiving_yards", "anytime_td"} <= markets


def test_quoted_nfl_prop_keeps_both_sides_and_does_not_invent_the_complement():
    card = build_card([{
        "game_id": "g",
        "home": "KC",
        "away": "BUF",
        "margin": 3.0,
        "total": 47.0,
        "quotes": [
            {"market": "moneyline", "side": "HOME", "american_odds": -140},
            {"market": "player_pass_yds", "entity_id": "qb", "side": "OVER", "line": 245.5, "american_odds": -115},
        ],
    }])
    moneyline = {row["selection"]: row for row in card["full_board"]["rows"] if row["market"] == "moneyline" and row["game_id"] == "g"}
    assert moneyline["HOME"]["model_p"] is not None
    assert moneyline["AWAY"]["reason"] == "COMPLEMENT_SIDE_NOT_QUOTED"
    props = {row["selection"]: row for row in card["full_board"]["rows"] if row["market"] == "passing_yards" and row["entity_id"] == "qb"}
    assert props["OVER"]["model_p"] is None
    assert props["UNDER"]["model_p"] is None
    assert props["UNDER"]["reason"] == "COMPLEMENT_SIDE_NOT_QUOTED"
    assert card["summary"]["catalog_complete"] is True
    text = render_markdown(card)
    assert "passing_yards" in text
    assert "OFFICIAL" not in text
    assert "Truth Gate" not in text
    assert "model_p" not in text


def test_cfb_machine_summary_requires_full_prop_side_total_catalog():
    board = emit_all_props_side_totals(sport="CFB")
    assert catalog_complete(board["summary"]) is True
    script = Path("scripts/run_nfl_auto.py").read_text(encoding="utf-8")
    assert "catalog_complete" not in script
    assert "football_full_board" not in script
    workflow = Path(".github/workflows/auto-nfl.yml").read_text(encoding="utf-8")
    assert "SPORTSEDGE_ODDS_API_KEY" not in workflow
    assert "catalog_complete" in workflow
    payload = json.loads(Path("config/football_prop_engine_surface.json").read_text(encoding="utf-8"))
    assert payload["sports"]["NFL"]["engine_state"] == "NO_ENGINE"
    assert payload["sports"]["CFB"]["engine_state"] == "NO_ENGINE"


def test_nfl_phone_card_lists_both_sides_of_props_sides_and_totals():
    from scripts.run_nfl_lines_card import attach_nfl_phone_board
    from scripts.render_nfl_myspari_card import both_side_section

    payload = attach_nfl_phone_board({
        "games": [{
            "away": "BUF",
            "home": "KC",
            "markets": [
                {"market": "moneyline", "away_or_over_price": 130, "home_or_under_price": -150, "raw": "ML"},
                {"market": "total", "line": 47.5, "away_or_over_price": -110, "home_or_under_price": -110, "raw": "total"},
                {"market": "passing_yards", "player": "Mahomes", "line": 245.5, "away_or_over_price": -115, "home_or_under_price": -105, "raw": "PassYards"},
            ],
        }]
    })
    assert payload["summary"]["both_sides"] is True
    assert payload["summary"]["catalog_complete"] is True
    text = both_side_section(payload)
    assert "passing_yards" in text
    assert "Mahomes" in text
    assert "OVER" in text and "UNDER" in text
    assert "HOME" in text and "AWAY" in text
    assert "OFFICIAL" not in text
    assert payload["full_board"]["authority"] != "OFFICIAL"


def test_cfb_card_payload_keeps_both_sides_without_changing_bets():
    from scripts.run_cfb_sdv_card_v2 import attach_cfb_both_sides

    payload = attach_cfb_both_sides({
        "results": [
            {"game_id": "g", "matchup": "A @ B", "market": "TOTAL", "side": "OVER", "line": 54.5, "american_odds": -110, "model_p": 0.52, "edge": 0.01, "bet_status": "PASS"},
            {"game_id": "g", "matchup": "A @ B", "market": "TOTAL", "side": "UNDER", "line": 54.5, "american_odds": -110, "model_p": 0.48, "edge": -0.01, "bet_status": "PASS"},
        ]
    })
    totals = {row["selection"] for row in payload["full_board"]["rows"] if row["market"] == "total" and row["game_id"] == "g"}
    assert totals == {"OVER", "UNDER"}
    assert payload["both_sides"] is True
    assert payload["catalog_complete"] is True
    assert payload["results"][0]["bet_status"] == "PASS"
