import pytest
from sportsedge.sports.nhl.roster_shots import NHLRosterShotRole, simulate_roster_shots, shots_over


def role(pid, weight=1.0, team="HOME"):
    return NHLRosterShotRole(pid, team, "2026-10-01T12:00:00Z", "fixture", "v1", weight, "CONFIRMED")


def test_roster_shots_are_deterministic_and_conserve_team_sog():
    team_shots=(30, 27, 41, 0)
    roles=[role("a",3), role("b",2), role("c",1)]
    a=simulate_roster_shots(team_shots, roles, team="HOME", version="v1", game_seed=123)
    b=simulate_roster_shots(team_shots, roles, team="HOME", version="v1", game_seed=123)
    assert a == b
    for i,total in enumerate(team_shots):
        assert sum(values[i] for values in a.shots.values()) == total


def test_player_over_probability_comes_from_shared_paths():
    paths=simulate_roster_shots((3,3,3,3), [role("a",3),role("b",1)], team="HOME", version="v1", game_seed=7)
    win,push,loss=shots_over(paths,"a",2.0)
    assert win + push + loss == pytest.approx(1.0)


def test_rejects_bad_rosters_and_shot_paths():
    with pytest.raises(ValueError):
        simulate_roster_shots((10,), [role("a"),role("a")], team="HOME", version="v1", game_seed=1)
    with pytest.raises(ValueError):
        simulate_roster_shots((10,), [role("a"),role("b",team="AWAY")], team="HOME", version="v1", game_seed=1)
    with pytest.raises(ValueError):
        simulate_roster_shots((-1,), [role("a")], team="HOME", version="v1", game_seed=1)
    with pytest.raises(ValueError):
        simulate_roster_shots((10,), [role("a",0),role("b",0)], team="HOME", version="v1", game_seed=1)
