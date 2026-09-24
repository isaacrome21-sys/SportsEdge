from sportsedge.sports.nhl.market_capabilities import capability_for


def test_full_game_markets_require_coherent_hockey_engine():
    for market in ("MONEYLINE", "PUCK_LINE", "TOTAL", "HOME_TEAM_TOTAL", "AWAY_TEAM_TOTAL"):
        cap = capability_for(market)
        assert cap.status == "REQUIRES_ENGINE"
        assert "shared_regulation_goal_paths" in cap.required_state
        assert "goalie_state" in cap.required_state
        assert "team_strength_state" in cap.required_state


def test_moneyline_requires_overtime_and_shootout_state():
    cap = capability_for("MONEYLINE")
    assert "overtime_shootout_state" in cap.required_state


def test_regulation_market_is_distinct_from_final_moneyline():
    cap = capability_for("REGULATION_MONEYLINE")
    assert cap.status == "REQUIRES_ENGINE"
    assert "overtime_shootout_state" not in cap.required_state


def test_period_and_player_markets_fail_closed_until_real_state_exists():
    for market in ("PERIOD_MONEYLINE", "PERIOD_TOTAL", "PLAYER_SHOTS", "PLAYER_POINTS", "PLAYER_GOALS"):
        assert capability_for(market).status == "NO_ENGINE"


def test_unknown_market_fails_closed():
    cap = capability_for("first_goal_scorer")
    assert cap.status == "NO_ENGINE"
    assert cap.required_state == ()


def test_coherent_period_and_player_markets_are_engine_backed():
    for market in ("PERIOD_MONEYLINE", "PERIOD_TOTAL", "PLAYER_SHOTS", "PLAYER_POINTS", "PLAYER_GOALS"):
        assert capability_for(market).status == "REQUIRES_ENGINE"


def test_unmodeled_goalie_and_counting_props_fail_closed():
    for market in ("GOALIE_SAVES", "PLAYER_BLOCKS", "PLAYER_HITS"):
        assert capability_for(market).status == "NO_ENGINE"
