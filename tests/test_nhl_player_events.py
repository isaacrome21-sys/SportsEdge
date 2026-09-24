import pytest
from sportsedge.sports.nhl.simulation import NHLGameState, simulate_game_paths
from sportsedge.sports.nhl.player_events import NHLPlayerEventRole, simulate_player_events, goals_over, points_over


def role(**kw):
    base=dict(player_id="p1",team="HOME",captured_at="2026-10-10T00:00:00Z",source="fixture",version="v1",goal_share=.18,primary_assist_share=.22,secondary_assist_share=.16,lineup_status="CONFIRMED")
    base.update(kw); return NHLPlayerEventRole(**base)


def test_event_paths_are_deterministic_and_cannot_exceed_team_goals():
    game=simulate_game_paths(NHLGameState("g",3.1,2.7),simulations=1000,seed=11)
    a=simulate_player_events(game,role()); b=simulate_player_events(game,role())
    assert a==b
    for g,a1,p,t in zip(a.goals,a.assists,a.points,game.home_regulation):
        assert g <= t and a1 <= t and p == g+a1


def test_goal_and_point_market_probability_mass():
    game=simulate_game_paths(NHLGameState("g",3.1,2.7),simulations=1000,seed=12)
    paths=simulate_player_events(game,role())
    assert sum(goals_over(paths,.5)) == pytest.approx(1)
    assert sum(points_over(paths,.5)) == pytest.approx(1)


def test_event_role_fails_closed():
    with pytest.raises(ValueError): role(team="H").validate()
    with pytest.raises(ValueError): role(goal_share=1.1).validate()
    with pytest.raises(ValueError): role(lineup_status="LIKELY").validate()
