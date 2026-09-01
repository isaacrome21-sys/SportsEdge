from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.live_adapters import CFBLiveAdapter, MLBLiveAdapter, NFLLiveAdapter
from sportsedge.live_engine import (
    LiveEngineError,
    LiveGameState,
    LiveModelOutput,
    PairedLiveQuote,
    paired_no_vig_probability,
    run_live_engine,
)


NOW = datetime(2026, 8, 29, 22, 0, tzinfo=timezone.utc)


def quote(**overrides):
    values = dict(
        book="DK",
        market="TOTAL",
        contract="UNDER 40.5",
        focal_odds=-115,
        opposite_odds=-115,
        observed_at=NOW - timedelta(seconds=5),
        active=True,
    )
    values.update(overrides)
    return PairedLiveQuote(**values)


def football_state(sport="NFL", **state_overrides):
    live = {
        "down": 1,
        "distance": 10,
        "yardline_100": 75,
        "timeouts_home": 3,
        "timeouts_away": 3,
        "plays_home": 20,
        "plays_away": 18,
    }
    live.update(state_overrides)
    return LiveGameState(
        sport=sport,
        event_id="game-1",
        observed_at=NOW - timedelta(seconds=4),
        period="Q2",
        clock_seconds=840,
        home_score=0,
        away_score=0,
        possession="HOME",
        state=live,
    )


def test_no_vig_even_pair_is_half():
    assert paired_no_vig_probability(-115, -115) == pytest.approx(0.5)


def test_missing_model_p_blocks():
    result = run_live_engine(
        game_state=football_state(),
        quote=quote(),
        model=LiveModelOutput(None, deployed=False, validated=False),
        edge_floor=0.03,
        now=NOW,
    )
    assert result.bet_status == "BLOCKED"
    assert result.reason == "MODEL_P_MISSING"


def test_unvalidated_model_blocks():
    result = run_live_engine(
        game_state=football_state(),
        quote=quote(),
        model=LiveModelOutput(0.60, deployed=True, validated=False, model_version="nfl-live-shadow"),
        edge_floor=0.03,
        now=NOW,
    )
    assert result.bet_status == "BLOCKED"
    assert result.reason == "LIVE_MODEL_NOT_VALIDATED"


def test_stale_quote_blocks():
    result = run_live_engine(
        game_state=football_state(),
        quote=quote(observed_at=NOW - timedelta(seconds=60)),
        model=LiveModelOutput(0.60, deployed=True, validated=True),
        edge_floor=0.03,
        now=NOW,
    )
    assert result.bet_status == "BLOCKED"
    assert result.reason == "STALE_LIVE_QUOTE"


def test_validated_positive_edge_can_be_official():
    result = run_live_engine(
        game_state=football_state(),
        quote=quote(focal_odds=-110, opposite_odds=-110),
        model=LiveModelOutput(0.60, deployed=True, validated=True, model_version="fixture-v1"),
        edge_floor=0.03,
        now=NOW,
    )
    assert result.bet_status == "OFFICIAL_BET"
    assert result.model_p == pytest.approx(0.60)
    assert result.no_vig_market_p == pytest.approx(0.50)
    assert result.edge == pytest.approx(0.10)
    assert result.ev_per_dollar > 0
    assert 0 < result.kelly_fraction <= 0.05


def test_nfl_adapter_requires_down_distance_and_field_position():
    state = football_state()
    features = NFLLiveAdapter().transform(state).features
    assert features["down"] == 1
    assert features["possession"] == "HOME"


def test_cfb_adapter_requires_pregame_ratings():
    with pytest.raises(LiveEngineError):
        CFBLiveAdapter().transform(football_state("CFB"))


def test_cfb_adapter_accepts_required_ratings():
    state = football_state("CFB", home_pregame_rating=7.2, away_pregame_rating=4.1)
    result = CFBLiveAdapter().transform(state)
    assert result.features["home_pregame_rating"] == 7.2


def test_mlb_adapter_validates_base_out_count_state():
    state = LiveGameState(
        sport="MLB",
        event_id="mlb-1",
        observed_at=NOW,
        period="TOP_5",
        clock_seconds=None,
        home_score=2,
        away_score=1,
        state={
            "inning": 5,
            "inning_half": "TOP",
            "outs": 1,
            "balls": 2,
            "strikes": 1,
            "bases_occupied": [1, 3],
            "batting_team": "AWAY",
            "home_pregame_rating": 0.55,
            "away_pregame_rating": 0.45,
        },
    )
    result = MLBLiveAdapter().transform(state)
    assert result.features["outs"] == 1
    assert result.features["bases_occupied"] == [1, 3]
