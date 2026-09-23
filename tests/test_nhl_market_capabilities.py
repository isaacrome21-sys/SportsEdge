from sportsedge.sports.nhl.market_capabilities import capability_for

def test_full_game_markets_require_coherent_hockey_engine():
    for market in ("MONEYLINE","PUCK_LINE","TOTAL","HOME_TEAM_TOTAL","AWAY_TEAM_TOTAL"):
        cap=capability_for(market)
        assert cap.status=="REQUIRES_ENGINE"
        assert "shared_regulation_goal_paths" in cap.required_state

def test_completed_period_and_player_engines_are_registered():
    for market in ("PERIOD_MONEYLINE","PERIOD_TOTAL","PLAYER_SHOTS","PLAYER_POINTS","PLAYER_GOALS"):
        cap=capability_for(market)
        assert cap.status=="REQUIRES_ENGINE"
        assert cap.required_state

def test_unbuilt_and_unknown_markets_fail_closed():
    for market in ("GOALIE_SAVES","PLAYER_BLOCKS","PLAYER_HITS","PLAYER_ASSISTS","EXACT_SCORE"):
        assert capability_for(market).status=="NO_ENGINE"
