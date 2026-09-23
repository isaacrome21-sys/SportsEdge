from sportsedge.sports.nhl.market_capabilities import capability_for


def test_full_game_markets_require_coherent_hockey_engine():
    for market in ("MONEYLINE", "PUCK_LINE", "TOTAL", "HOME_TEAM_TOTAL", "AWAY_TEAM_TOTAL"):
        cap = capability_for(market)
        assert cap.status == "REQUIRES_ENGINE"
        assert "shared_regulation_goal_paths" in cap.required_state
        assert "goalie_state" in cap.required_state
        assert "team_strength_state" in cap.required_state


def test_moneyline_requires_overtime_and_shootout_state():
    assert "overtime_shootout_state" in capability_for("MONEYLINE").required_state


def test_regulation_market_is_distinct_from_final_moneyline():
    cap = capability_for("REGULATION_MONEYLINE")
    assert cap.status == "REQUIRES_ENGINE"
    assert "overtime_shootout_state" not in cap.required_state


def test_completed_period_and_player_engines_are_registered():
    for market in ("PERIOD_MONEYLINE", "PERIOD_TOTAL", "PLAYER_SHOTS", "PLAYER_POINTS", "PLAYER_GOALS"):
        cap = capability_for(market)
        assert cap.status == "REQUIRES_ENGINE"
        assert cap.required_state


def test_unbuilt_and_unknown_markets_fail_closed():
    for market in ("GOALIE_SAVES", "PLAYER_BLOCKS", "PLAYER_HITS", "PLAYER_ASSISTS", "EXACT_SCORE"):
        cap = capability_for(market)
        assert cap.status == "NO_ENGINE"


def test_unknown_market_has_no_required_state():
    assert capability_for("first_goal_scorer").required_state == ()
