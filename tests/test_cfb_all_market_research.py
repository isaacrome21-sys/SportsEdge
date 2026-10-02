from datetime import datetime, timezone

from scripts.run_cfb_all_market_research import build_board


NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def test_game_model_rows_take_priority_and_remain_blocked_leans():
    game = {"report": {"results": [{
        "game_id": "g1", "market": "SPREAD", "side": "HOME", "line": -3.5,
        "american_odds": -110, "model_p": 0.58, "fair_market_p": 0.50,
        "edge": 0.08, "ev_per_dollar": 0.107,
    }]}}
    paper = {"candidates": [{
        "game_id": "g1", "market": "SPREAD", "side": "Home", "line": -3.5,
        "draftkings_odds": -110, "market_consensus_no_vig_p": 0.54,
        "market_consensus_edge": 0.016, "market_consensus_ev_per_dollar": 0.03,
    }]}
    board = build_board(game_model=game, paper_market=paper, prop_candidate=None, generated_at=NOW)
    assert board["game_lane"] == "GAME_MODEL"
    assert len(board["rows"]) == 1
    assert board["rows"][0]["presentation_label"] == "LEAN"
    assert board["rows"][0]["model_p"] == 0.58
    assert board["rows"][0]["bet_status"] == "BLOCKED"
    assert board["summary"]["official_bets"] == 0
    assert not any(board["authority"].values())


def test_paper_fallback_never_becomes_model_p():
    paper = {"candidates": [{
        "game_id": "g1", "market": "TOTAL", "side": "Over", "line": 49.5,
        "draftkings_odds": 105, "market_consensus_no_vig_p": 0.55,
        "market_consensus_edge": 0.062, "market_consensus_ev_per_dollar": 0.1275,
    }]}
    board = build_board(game_model=None, paper_market=paper, prop_candidate=None, generated_at=NOW)
    assert board["game_lane"] == "MARKET_CONSENSUS"
    assert board["rows"][0]["model_p"] is None
    assert board["rows"][0]["presentation_label"] == "PAPER"
    assert board["rows"][0]["decision_tier"] == "MARKET_CONTEXT"


def test_prop_candidates_join_same_board_as_blocked_leans():
    prop = {"report": {"results": [{
        "game_id": "g1", "provider_market": "player_pass_yds",
        "player_id": "p1", "player_name": "QB One", "side": "OVER",
        "line": 249.5, "american_odds": -110, "model_p": 0.61,
        "fair_market_p": 0.52, "edge": 0.09, "ev_per_dollar": 0.16,
    }]}}
    board = build_board(game_model=None, paper_market=None, prop_candidate=prop, generated_at=NOW)
    assert board["prop_lane"] == "PLAYER_PROP_MODEL"
    assert board["summary"]["prop_rows"] == 1
    row = board["rows"][0]
    assert row["presentation_label"] == "LEAN"
    assert row["bet_status"] == "BLOCKED"
    assert row["official"] is False
