import pytest

from sportsedge.sports.nhl.event_binding import simulate_bound_roster_events
from sportsedge.sports.nhl.role_binding import bind_historical_roles
from sportsedge.sports.nhl.role_history import NHLHistoricalRoleShare
from sportsedge.sports.nhl.simulation import NHLGamePaths


def _share(player, goal):
    return NHLHistoricalRoleShare(
        player_id=player, team_id="10", cutoff="2026-01-02T00:00:00Z",
        source="nhl@v1", version="role-v1", games=10, shot_weight=2.0,
        goal_weight=goal, primary_assist_weight=.2, secondary_assist_weight=.1,
        history_sha256="a"*64,
    )


def _game():
    return NHLGamePaths(
        home_regulation=(2, 0, 3), away_regulation=(1, 1, 2),
        home_final=(2, 0, 3), away_final=(1, 2, 2), seed=7,
    )


def _bound():
    return bind_historical_roles(
        (_share("p1", .6), _share("p2", .4)), team="HOME",
        lineup_status="CONFIRMED", active_player_ids={"p1", "p2"},
    )


def test_bound_events_reconcile_every_team_goal_path():
    out=simulate_bound_roster_events(
        _game(), _bound(), team="HOME",
        puck_drop="2026-01-03T00:00:00Z", version="bind-v1",
    )
    for i,total in enumerate(_game().home_regulation):
        assert sum(v[i] for v in out.events.goals.values()) == total
    assert out.history_sha256 == "a"*64


def test_bound_events_are_deterministic():
    kwargs=dict(team="HOME", puck_drop="2026-01-03T00:00:00Z", version="bind-v1")
    assert simulate_bound_roster_events(_game(), _bound(), **kwargs) == simulate_bound_roster_events(_game(), _bound(), **kwargs)


def test_bound_events_reject_post_drop_role_cutoff():
    with pytest.raises(ValueError, match="PIT violation"):
        simulate_bound_roster_events(
            _game(), _bound(), team="HOME",
            puck_drop="2026-01-01T00:00:00Z", version="bind-v1",
        )


def test_bound_events_reject_team_mismatch():
    with pytest.raises(ValueError, match="match requested team"):
        simulate_bound_roster_events(
            _game(), _bound(), team="AWAY",
            puck_drop="2026-01-03T00:00:00Z", version="bind-v1",
        )
