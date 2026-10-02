from __future__ import annotations

import json
from pathlib import Path

from sportsedge.football_prop_extended_run_machine import PROVIDER_MARKETS
from sportsedge.sports.cfb.research_card import assemble_cfb_research_card

ROOT = Path(__file__).resolve().parents[1]


def test_research_surface_matches_extended_prop_provider_surface_without_promotion():
    surface = json.loads((ROOT / "config/cfb_research_market_surface_v1.json").read_text())
    assert set(surface["player_prop_candidate_markets"]) == set(PROVIDER_MARKETS)
    assert surface["player_prop_lane"]["production_engine_state"] == "NO_ENGINE"
    assert surface["governance"]["promotion_authority"] is False
    authoritative = json.loads((ROOT / "config/football_prop_engine_surface.json").read_text())
    assert authoritative["sports"]["CFB"]["engine_state"] == "NO_ENGINE"


def test_full_research_card_combines_game_and_prop_leans_but_never_official():
    game = {
        "results": [
            {
                "game_id": "g1", "market": "SPREAD", "side": "HOME",
                "line": -3.5, "american_odds": -110, "model_p": 0.56,
                "fair_market_p": 0.50, "edge": 0.06, "ev_per_dollar": 0.07,
                "bet_status": "BLOCKED", "reason": "CFB_PROMOTION_EVIDENCE_REQUIRED",
                "distribution_sha256": "a" * 64,
            },
            {
                "game_id": "g1", "market": "TOTAL", "side": "OVER",
                "line": 55.5, "american_odds": -110, "model_p": 0.52,
                "fair_market_p": 0.50, "edge": 0.02, "ev_per_dollar": 0.01,
                "bet_status": "BLOCKED", "reason": "CFB_QUOTE_STALE",
                "distribution_sha256": "a" * 64,
            },
        ]
    }
    props = {
        "report": {
            "results": [
                {
                    "game_id": "g1", "provider_market": "player_pass_yds",
                    "market": "passing_yards", "player_id": "p1",
                    "player_name": "Quarter Back", "side": "OVER",
                    "line": 249.5, "american_odds": -110, "model_p": 0.59,
                    "fair_market_p": 0.51, "edge": 0.08, "ev_per_dollar": 0.11,
                    "quote_fresh": True, "model_candidate_status": "READY",
                    "distribution_sha256": "b" * 64,
                }
            ]
        }
    }
    card = assemble_cfb_research_card(game_payload=game, prop_payload=props)
    assert card["run_status"] == "RESEARCH_LEANS_AVAILABLE"
    assert card["summary"]["game_rows"] == 2
    assert card["summary"]["prop_rows"] == 1
    assert card["summary"]["lean_rows"] == 2
    assert card["summary"]["official_bets"] == 0
    assert {row["display_status"] for row in card["rows"]} == {"LEAN", "BLOCKED"}
    assert all(row["official_eligible"] is False for row in card["rows"])
    assert card["governance"]["promotion_authority"] is False


def test_stale_or_uncandidate_prop_does_not_become_lean():
    card = assemble_cfb_research_card(
        game_payload={"results": []},
        prop_payload={"results": [{
            "game_id": "g1", "provider_market": "player_anytime_td",
            "market": "touchdowns", "player_id": "p1", "player_name": "Runner",
            "side": "YES", "line": 0.5, "american_odds": 120,
            "model_p": 0.48, "quote_fresh": False,
            "model_candidate_status": "BLOCKED",
            "reason": "CFB_PROP_QUOTE_STALE",
        }]},
    )
    assert card["summary"]["lean_rows"] == 0
    assert card["rows"][0]["display_status"] == "BLOCKED"
