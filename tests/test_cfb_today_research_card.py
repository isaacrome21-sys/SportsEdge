from sportsedge.sports.cfb.today_research_card import assemble_cfb_today_research_card


def test_numeric_game_model_takes_priority_over_paper_context():
    game = {"report": {"results": [{
        "game_id": "g1", "market": "SPREAD", "side": "HOME",
        "line": -3.5, "american_odds": -110, "model_p": 0.58,
        "fair_market_p": 0.50, "edge": 0.08, "ev_per_dollar": 0.10,
        "bet_status": "BLOCKED", "reason": "CFB_GAME_RESEARCH_ARTIFACT_NOT_PRODUCTION_FROZEN",
    }]}}
    paper = {"candidates": [{
        "game_id": "g1", "market": "SPREAD", "side": "Home",
        "line": -3.5, "draftkings_odds": -110,
        "market_consensus_no_vig_p": 0.54,
        "market_consensus_edge": 0.02,
        "market_consensus_ev_per_dollar": 0.04,
    }]}
    card = assemble_cfb_today_research_card(
        game_model_payload=game, paper_market_payload=paper
    )
    assert card["game_lane"] == "GAME_MODEL"
    assert card["summary"]["game_rows"] == 1
    assert card["summary"]["paper_rows"] == 0
    assert card["rows"][0]["display_status"] == "LEAN"
    assert card["rows"][0]["model_p"] == 0.58
    assert card["summary"]["official_bets"] == 0


def test_paper_fallback_is_visible_but_never_model_p():
    paper = {"candidates": [{
        "game_id": "g1", "market": "TOTAL", "side": "Over",
        "line": 49.5, "draftkings_odds": 105,
        "market_consensus_no_vig_p": 0.55,
        "market_consensus_edge": 0.06,
        "market_consensus_ev_per_dollar": 0.12,
        "peer_books_used": 3,
        "line_identity_rule": "EXACT_THRESHOLD_ONLY",
    }]}
    card = assemble_cfb_today_research_card(paper_market_payload=paper)
    assert card["game_lane"] == "MARKET_CONSENSUS"
    assert card["run_status"] == "PAPER_CONTEXT_AVAILABLE"
    row = card["rows"][0]
    assert row["display_status"] == "PAPER"
    assert row["model_p"] is None
    assert row["official_eligible"] is False
    assert card["governance"]["paper_market_context_can_create_model_p"] is False


def test_prop_leans_join_paper_game_context_without_authority_leak():
    prop = {"report": {"results": [{
        "game_id": "g1", "provider_market": "player_pass_yds",
        "market": "passing_yards", "player_id": "p1",
        "player_name": "QB One", "side": "OVER",
        "line": 249.5, "american_odds": -110, "model_p": 0.61,
        "fair_market_p": 0.52, "edge": 0.09, "ev_per_dollar": 0.16,
        "quote_fresh": True, "model_candidate_status": "READY",
    }]}}
    paper = {"candidates": [{
        "game_id": "g1", "market": "MONEYLINE", "side": "Home",
        "line": None, "draftkings_odds": 120,
        "market_consensus_no_vig_p": 0.48,
        "market_consensus_edge": 0.02,
        "market_consensus_ev_per_dollar": 0.05,
    }]}
    card = assemble_cfb_today_research_card(
        paper_market_payload=paper, prop_payload=prop
    )
    assert card["summary"]["prop_rows"] == 1
    assert card["summary"]["lean_rows"] == 1
    assert card["summary"]["paper_rows"] == 1
    assert card["summary"]["official_bets"] == 0
    assert all(row["official_eligible"] is False for row in card["rows"])
