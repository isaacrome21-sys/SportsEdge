import pytest
from sportsedge.sports.nhl.simulation import NHLGameState, simulate_game_paths
from sportsedge.sports.nhl.player_props import NHLPlayerRole, simulate_player_shots, shots_over


def role(**kw):
    base=dict(player_id="p1",team="H",captured_at="2026-10-10T00:00:00Z",source="fixture",version="v1",projected_toi_minutes=19,projected_pp_toi_minutes=3,shots_per_60=9,pp_shots_per_60=15,lineup_status="CONFIRMED")
    base.update(kw); return NHLPlayerRole(**base)


def test_shot_paths_deterministic_and_aligned_to_game_paths():
    game=simulate_game_paths(NHLGameState("g",3,2.7),simulations=500,seed=7)
    a=simulate_player_shots(game,role()); b=simulate_player_shots(game,role())
    assert a==b and len(a.shots)==game.simulations


def test_shot_market_probability_mass():
    game=simulate_game_paths(NHLGameState("g",3,2.7),simulations=1000,seed=8)
    mass=shots_over(simulate_player_shots(game,role()),2.5)
    assert sum(mass)==pytest.approx(1)


def test_role_fails_closed():
    with pytest.raises(ValueError):
        role(lineup_status="LIKELY").validate()
    with pytest.raises(ValueError):
        role(projected_toi_minutes=2,projected_pp_toi_minutes=3).validate()
