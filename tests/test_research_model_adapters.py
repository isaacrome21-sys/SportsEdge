"""Tests for the thin research model adapters that feed the pricing bridge."""
from __future__ import annotations

from unittest.mock import patch

from sportsedge.research_model_adapters import (
    football_player_stat_to_bridge_rows,
    free_game_projection_to_bridge_rows,
    mlb_pitcher_to_bridge_rows,
)


def test_mlb_pitcher_adapter_emits_priced_research_row():
    fake_result = {"p": 0.58, "p_push": 0.0}
    with patch("sportsedge.research_model_adapters.price_pitcher_market", return_value=fake_result):
        rows = mlb_pitcher_to_bridge_rows(
            game_id="mlb-2026-10-12-ny-bos",
            player_id="pitcher-123",
            market="PITCHER_K",
            side="OVER",
            line=6.5,
            features={"history_pool": [{"strikeouts": 7, "outs": 18, "earned_runs": 2, "hits_allowed": 5, "walks_allowed": 2}] * 5},
            kickoff_utc="2026-10-12T19:05:00Z",
            home_team="BOS",
            away_team="NYY",
        )
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "PRICED_RESEARCH"
    assert row["market_blind"] is True
    assert row["estimate_p"] == 0.58
    assert row["model_source"] == "mlb_pitcher_joint_engine"
    assert row["player_id"] == "pitcher-123"
    assert row["line"] == 6.5


def test_mlb_pitcher_adapter_fails_closed_on_engine_error():
    with patch("sportsedge.research_model_adapters.price_pitcher_market", side_effect=ValueError("NO_HISTORY")):
        rows = mlb_pitcher_to_bridge_rows(
            game_id="g1",
            player_id="p1",
            market="PITCHER_K",
            side="OVER",
            line=5.5,
            features={},
            kickoff_utc="2026-10-12T19:05:00Z",
        )
    assert rows[0]["status"] == "NO_MODEL_OR_MARKET"
    assert "NO_HISTORY" in rows[0]["reason"]


def test_football_player_stat_adapter_emits_row():
    fake_masses = {"over": 0.61, "under": 0.35, "push": 0.04}
    with patch("sportsedge.research_model_adapters.derive_player_stat_market", return_value=fake_masses):
        rows = football_player_stat_to_bridge_rows(
            sport="NFL",
            game_id="nfl-2026-10-12-buf-lar",
            player_id="wr-456",
            stat="receiving_yards",
            line=64.5,
            side="OVER",
            paths=[object()],
            kickoff_utc="2026-10-12T20:20:00Z",
            home_team="LAR",
            away_team="BUF",
        )
    assert rows[0]["status"] == "PRICED_RESEARCH"
    assert rows[0]["estimate_p"] == 0.61
    assert rows[0]["push_p"] == 0.04
    assert rows[0]["market"] == "PLAYER_RECEIVING_YARDS"
    assert rows[0]["model_source"] == "nfl_player_stat_paths"


def test_football_adapter_fails_closed_when_paths_missing():
    with patch("sportsedge.research_model_adapters.derive_player_stat_market", side_effect=ValueError("ATTRIBUTED_PATHS_EMPTY")):
        rows = football_player_stat_to_bridge_rows(
            sport="CFB",
            game_id="cfb-1",
            player_id="qb-1",
            stat="passing_yards",
            line=250.5,
            side="OVER",
            paths=[],
            kickoff_utc="2026-10-11T23:00:00Z",
        )
    assert rows[0]["status"] == "NO_MODEL_OR_MARKET"
    assert "ATTRIBUTED_PATHS_EMPTY" in rows[0]["reason"]


def test_free_game_projection_adapter():
    rows = free_game_projection_to_bridge_rows(
        sport="NFL",
        game_id="nfl-buf-lar",
        market="TOTAL",
        side="UNDER",
        estimate_p=0.62,
        push_p=0.0,
        line=54.5,
        kickoff_utc="2026-10-12T20:20:00Z",
        home_team="LAR",
        away_team="BUF",
    )
    assert rows[0]["status"] == "PRICED_RESEARCH"
    assert rows[0]["market_blind"] is True
    assert rows[0]["estimate_p"] == 0.62
    assert rows[0]["model_source"] == "free_independent_score_heuristic"


def test_free_adapter_rejects_invalid_probability():
    rows = free_game_projection_to_bridge_rows(
        sport="MLB",
        game_id="g",
        market="ML",
        side="HOME",
        estimate_p=1.2,
        kickoff_utc="2026-10-12T19:00:00Z",
    )
    assert rows[0]["status"] == "NO_MODEL_OR_MARKET"
