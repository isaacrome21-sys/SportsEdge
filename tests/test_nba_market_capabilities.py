from sportsedge.sports.nba.market_capabilities import capability_for


def test_core_game_markets_require_shared_engine():
    for market in ("MONEYLINE", "SPREAD", "TOTAL", "HOME_TEAM_TOTAL", "AWAY_TEAM_TOTAL"):
        cap = capability_for(market)
        assert cap.status == "REQUIRES_ENGINE"
        assert "shared_possession_paths" in cap.required_state
        assert "rotation_state" in cap.required_state


def test_period_markets_require_explicit_period_paths():
    for market in ("FIRST_HALF_SPREAD", "FIRST_HALF_TOTAL", "QUARTER_SPREAD", "QUARTER_TOTAL"):
        cap = capability_for(market)
        assert cap.status == "REQUIRES_ENGINE"
        assert "period_paths" in cap.required_state


def test_player_markets_require_minutes_and_shared_paths():
    for market in ("PLAYER_POINTS", "PLAYER_REBOUNDS", "PLAYER_ASSISTS", "PLAYER_THREES", "PLAYER_PRA", "PLAYER_PR", "PLAYER_PA", "PLAYER_RA"):
        cap = capability_for(market)
        assert cap.status == "REQUIRES_ENGINE"
        assert "minutes_distribution" in cap.required_state
        assert "shared_player_stat_paths" in cap.required_state


def test_combo_props_explicitly_forbid_independent_marginals():
    for market in ("PLAYER_PRA", "PLAYER_PR", "PLAYER_PA", "PLAYER_RA"):
        assert "same-path" in capability_for(market).reason


def test_unvalidated_tail_and_first_event_markets_fail_closed():
    for market in ("FIRST_BASKET", "DOUBLE_DOUBLE", "TRIPLE_DOUBLE", "UNKNOWN_THING"):
        assert capability_for(market).status == "NO_ENGINE"
