import pytest

from sportsedge.sports.nfl.market_context_props import (
    MarketContextPropError,
    run_market_context_props,
)


def test_market_context_sets_score_environment_without_game_picks():
    out = run_market_context_props(
        game_id="G1",
        home_team="HOME",
        away_team="AWAY",
        home_spread=-3.5,
        game_total=45.5,
        as_of="2026-10-05T16:00:00Z",
        n_sims=100,
        seed=7,
    )
    assert out["market_environment"]["fair_home_margin"] == pytest.approx(3.5)
    assert out["market_environment"]["game_total"] == pytest.approx(45.5)
    assert out["game_card"]["picks"] == []
    assert out["authority"]["creates_game_market_edge"] is False
    assert "attempt9_raw" not in out["model"]


def test_home_underdog_maps_to_negative_expected_margin():
    out = run_market_context_props(
        game_id="G2",
        home_team="HOME",
        away_team="AWAY",
        home_spread=2.5,
        game_total=42.0,
        as_of="2026-10-05T16:00:00Z",
        n_sims=50,
        seed=3,
    )
    assert out["market_environment"]["fair_home_margin"] == pytest.approx(-2.5)


def test_total_must_be_positive():
    with pytest.raises(MarketContextPropError, match="POSITIVE_REQUIRED"):
        run_market_context_props(
            game_id="G3",
            home_team="HOME",
            away_team="AWAY",
            home_spread=-3.0,
            game_total=0,
            as_of="2026-10-05T16:00:00Z",
        )
