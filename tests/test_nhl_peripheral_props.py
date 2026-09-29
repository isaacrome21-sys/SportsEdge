from sportsedge.sports.nhl.peripheral_props import (
    NHLPeripheralRole,
    NHLTeamPeripheralParameters,
    peripheral_over,
    simulate_roster_peripheral_paths,
    simulate_team_peripheral_paths,
)


def _roles():
    return (
        NHLPeripheralRole("p1", "HOME", "2026-09-29T12:00:00+00:00", "fixture", "v1", 2.0, 3.0, "CONFIRMED"),
        NHLPeripheralRole("p2", "HOME", "2026-09-29T12:00:00+00:00", "fixture", "v1", 1.0, 2.0, "CONFIRMED"),
        NHLPeripheralRole("p3", "HOME", "2026-09-29T12:00:00+00:00", "fixture", "v1", 1.0, 1.0, "CONFIRMED"),
    )


def test_team_and_roster_peripheral_paths_are_deterministic_and_conserve_events():
    params = NHLTeamPeripheralParameters("team-v1", 15.0, 22.0, "fixture", "a" * 64)
    team_paths = simulate_team_peripheral_paths("game-1", params, simulations=500, seed=9)
    first = simulate_roster_peripheral_paths(team_paths, _roles(), team="HOME", version="roster-v1", game_seed=9)
    second = simulate_roster_peripheral_paths(team_paths, _roles(), team="HOME", version="roster-v1", game_seed=9)
    assert first == second
    for i in range(team_paths.simulations):
        assert sum(values[i] for values in first.blocks.values()) == first.team_blocks[i]
        assert sum(values[i] for values in first.hits.values()) == first.team_hits[i]


def test_peripheral_over_preserves_probability_mass():
    params = NHLTeamPeripheralParameters("team-v1", 15.0, 22.0, "fixture", "b" * 64)
    team_paths = simulate_team_peripheral_paths("game-2", params, simulations=1000, seed=3)
    paths = simulate_roster_peripheral_paths(team_paths, _roles(), team="HOME", version="roster-v1", game_seed=3)
    for stat in ("blocks", "hits"):
        win, push, loss = peripheral_over(paths, player_id="p1", stat=stat, line=1.0)
        assert abs(win + push + loss - 1.0) < 1e-12


def test_mixed_team_roster_fails_closed():
    params = NHLTeamPeripheralParameters("team-v1", 5.0, 5.0, "fixture", "c" * 64)
    team_paths = simulate_team_peripheral_paths("game-3", params, simulations=10, seed=1)
    bad = list(_roles())
    bad.append(NHLPeripheralRole("away", "AWAY", "2026-09-29T12:00:00+00:00", "fixture", "v1", 1.0, 1.0, "CONFIRMED"))
    try:
        simulate_roster_peripheral_paths(team_paths, bad, team="HOME", version="v1", game_seed=1)
    except ValueError as exc:
        assert "mixed-team" in str(exc)
    else:
        raise AssertionError("mixed-team roster must fail closed")
