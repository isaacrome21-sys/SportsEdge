import pytest

from sportsedge.sports.nba.market_contract import assert_supported, capability


def test_full_game_markets_are_declared_from_shared_score_state():
    state = {"home_points", "away_points"}
    for market in ("MONEYLINE", "SPREAD", "TOTAL", "HOME_TEAM_TOTAL", "AWAY_TEAM_TOTAL"):
        assert assert_supported(market, state).supported


def test_player_props_are_not_claimed_before_player_engine_exists():
    for market in ("PLAYER_POINTS", "PLAYER_REBOUNDS", "PLAYER_ASSISTS", "PLAYER_THREES", "PLAYER_PRA"):
        cap = capability(market)
        assert cap.supported is False
        with pytest.raises(ValueError, match="NO_ENGINE"):
            assert_supported(market, {"player_minutes", "player_stat_paths"})


def test_period_markets_are_not_derived_from_final_score_paths():
    with pytest.raises(ValueError, match="NO_ENGINE"):
        assert_supported("FIRST_HALF_TOTAL", {"home_points", "away_points"})


def test_supported_market_requires_exact_state():
    with pytest.raises(ValueError, match="MISSING_STATE:SPREAD:away_points"):
        assert_supported("SPREAD", {"home_points"})


def test_unknown_market_fails_closed():
    cap = capability("first_basket")
    assert cap.supported is False
    assert cap.reason == "market is not registered in the NBA engine"
