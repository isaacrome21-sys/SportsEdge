import json
from pathlib import Path

from sportsedge.football_prop_extended_run_machine import PROVIDER_MARKETS
from sportsedge.sports.nfl.research_card import assemble_nfl_research_card, price_team_total_rows

ROOT = Path(__file__).resolve().parents[1]


def test_nfl_research_surface_matches_prop_provider_markets_without_promotion():
    surface = json.loads((ROOT / "config/nfl_research_market_surface_v1.json").read_text())
    assert set(surface["player_prop_candidate_markets"]) == set(PROVIDER_MARKETS)
    assert surface["player_prop_lane"]["production_engine_state"] == "NO_ENGINE"
    authoritative = json.loads((ROOT / "config/football_prop_engine_surface.json").read_text())
    assert authoritative["sports"]["NFL"]["engine_state"] == "NO_ENGINE"
    assert authoritative["sports"]["CFB"]["engine_state"] == "NO_ENGINE"
    assert surface["governance"]["promotion_authority"] is False


def test_nfl_card_prices_team_totals_from_existing_scores_and_keeps_props_research_only():
    distribution = [
        {"home_score": 24, "away_score": 17},
        {"home_score": 20, "away_score": 20},
        {"home_score": 14, "away_score": 27},
        {"home_score": 31, "away_score": 10},
    ]
    team_rows = price_team_total_rows(
        distribution,
        game_id="g1",
        home_total_line=21.5,
        away_total_line=20.5,
        distribution_sha256="a" * 64,
    )
    card = assemble_nfl_research_card(
        game_payload={
            "results": [
                {
                    "game_id": "g1",
                    "market": "SPREAD",
                    "side": "HOME",
                    "line": -3.5,
                    "american_odds": -110,
                    "model_p": 0.57,
                    "fair_market_p": 0.5,
                    "edge": 0.07,
                    "ev_per_dollar": 0.08,
                    "bet_status": "BLOCKED",
                    "reason": "NFL_PROMOTION_EVIDENCE_REQUIRED",
                    "distribution_sha256": "a" * 64,
                }
            ]
        },
        prop_payload={
            "results": [
                {
                    "game_id": "g1",
                    "provider_market": "player_pass_yds",
                    "market": "passing_yards",
                    "player_id": "p1",
                    "player_name": "Quarter Back",
                    "side": "OVER",
                    "line": 249.5,
                    "american_odds": -110,
                    "model_p": 0.6,
                    "quote_fresh": True,
                    "model_candidate_status": "READY",
                    "distribution_sha256": "b" * 64,
                }
            ]
        },
        team_total_rows=team_rows,
    )
    assert card["summary"]["side_rows"] == 1
    assert card["summary"]["total_rows"] == 2
    assert card["summary"]["prop_rows"] == 1
    assert card["summary"]["official_bets"] == 0
    assert card["run_status"] == "RESEARCH_LEANS_AVAILABLE"
    assert card["unsupported_or_not_promoted"]["first_half"] == "NO_ENGINE"
    home = next(row for row in card["rows"] if row["market"] == "TEAM_TOTAL" and row["side"] == "HOME")
    assert home["model_p"] == 0.5
    assert home["official_eligible"] is False
