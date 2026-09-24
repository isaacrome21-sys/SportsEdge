from sportsedge.sports.nba.markets import game_market_probability, period_market_probability, player_market_probability
from sportsedge.sports.nba.periods import NBAPeriodPaths
from sportsedge.sports.nba.player_stats import NBAPlayerStatPaths
from sportsedge.sports.nba.simulation import NBAGamePaths


def game():
    return NBAGamePaths((100,100,100),(110,100,105),(100,105,105),(110,101,106),(100,105,105),7)


def test_full_game_markets_use_paired_final_paths_and_preserve_pushes():
    g=game()
    ml=game_market_probability(g,"MONEYLINE","HOME")
    assert ml.win_probability == 2/3 and ml.lose_probability == 1/3
    total=game_market_probability(g,"TOTAL","OVER",line=211)
    assert total.win_probability == 0 and total.push_probability == 1/3
    spread=game_market_probability(g,"SPREAD","HOME",line=-1)
    assert spread.win_probability == 1/3 and spread.push_probability == 1/3


def test_team_total_and_away_spread_semantics():
    g=game()
    tt=game_market_probability(g,"HOME_TEAM_TOTAL","OVER",line=105)
    assert tt.win_probability == 2/3
    away=game_market_probability(g,"SPREAD","AWAY",line=1)
    assert away.win_probability == 1/3 and away.push_probability == 1/3


def test_period_markets_use_explicit_period_paths():
    p=NBAPeriodPaths(((30,20,30,30),(20,25,25,30)),((20,25,25,30),(25,25,25,30)),1,"fit")
    q=period_market_probability(p,"QUARTER_TOTAL","OVER",line=50,quarter=1)
    assert q.win_probability == 0 and q.push_probability == .5
    h=period_market_probability(p,"FIRST_HALF_SPREAD","HOME",line=-5)
    assert h.win_probability == 0 and h.push_probability == .5


def test_player_combos_are_same_path_sums():
    p=NBAPlayerStatPaths("p",(30,30),(20,10),(10,5),(5,10),(2,1),2,"role")
    pra=player_market_probability(p,"PLAYER_PRA","OVER",line=30)
    assert pra.win_probability == .5 and pra.lose_probability == .5
    pa=player_market_probability(p,"PLAYER_PA","UNDER",line=25)
    assert pa.win_probability == .5 and pa.push_probability == .5


def test_unsupported_market_fails_closed():
    import pytest
    with pytest.raises(ValueError):
        game_market_probability(game(),"FIRST_BASKET","HOME")
