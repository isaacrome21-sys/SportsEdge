from sportsedge.sports.nhl.simulation import NHLGamePaths
from sportsedge.sports.nhl.roster_events import NHLRosterEventRole,simulate_roster_events,roster_event_over

def role(pid,g=1,a=1):
    return NHLRosterEventRole(pid,"HOME","2026-10-01T12:00:00Z","fixture","v1",g,a,a,"CONFIRMED")

def game():
    return NHLGamePaths((3,2),(1,1),(3,2),(1,1),123)

def test_roster_events_are_deterministic_and_conserve_scorers():
    roles=[role("a",3),role("b",2),role("c",1)]
    x=simulate_roster_events(game(),roles,team="HOME",version="v1")
    y=simulate_roster_events(game(),roles,team="HOME",version="v1")
    assert x==y
    for i,total in enumerate(game().home_regulation):
        assert sum(v[i] for v in x.goals.values())==total

def test_assists_are_distinct_from_scorer_and_each_other_by_construction():
    roles=[role("a"),role("b"),role("c")]
    x=simulate_roster_events(game(),roles,team="HOME",version="v1",seed=7)
    for i,total in enumerate(game().home_regulation):
        assert sum(v[i] for v in x.assists.values())<=2*total
        assert all(x.points[p][i]==x.goals[p][i]+x.assists[p][i] for p in x.goals)

def test_roster_event_over_supports_assists_and_preserves_mass():
    roles=[role("a"),role("b"),role("c")]
    x=simulate_roster_events(game(),roles,team="HOME",version="v1",seed=17)
    for stat in ("goals","assists","points"):
        win,push,loss=roster_event_over(x,player_id="a",stat=stat,line=1.0)
        assert abs(win+push+loss-1.0)<1e-12

def test_rejects_duplicate_or_mixed_team_roles():
    import pytest
    with pytest.raises(ValueError): simulate_roster_events(game(),[role("a"),role("a")],team="HOME",version="v1")
    bad=NHLRosterEventRole("z","AWAY","2026-10-01T12:00:00Z","fixture","v1",1,1,1,"PROJECTED")
    with pytest.raises(ValueError): simulate_roster_events(game(),[role("a"),bad],team="HOME",version="v1")
