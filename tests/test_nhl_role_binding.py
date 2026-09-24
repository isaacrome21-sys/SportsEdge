import pytest
from sportsedge.sports.nhl.role_binding import bind_historical_roles
from sportsedge.sports.nhl.role_history import NHLHistoricalRoleShare


def _share(player, *, shot=2.0, goal=.2, digest="a"*64):
    return NHLHistoricalRoleShare(
        player_id=player, team_id="10", cutoff="2026-01-02T00:00:00Z",
        source="nhl@v1", version="role-v1", games=10,
        shot_weight=shot, goal_weight=goal, primary_assist_weight=.2,
        secondary_assist_weight=.1, history_sha256=digest)


def test_binding_filters_to_active_players_and_preserves_weights():
    bound = bind_historical_roles((_share("p2"), _share("p1", shot=3.0)),
        team="HOME", lineup_status="CONFIRMED", active_player_ids={"p1"})
    assert [r.player_id for r in bound.event_roles] == ["p1"]
    assert [r.shot_weight for r in bound.shot_roles] == [3.0]
    assert bound.cutoff == "2026-01-02T00:00:00Z"
    assert bound.history_sha256 == "a"*64
    assert bound.event_roles[0].version.startswith("role-v1:")


def test_binding_is_order_deterministic():
    a = bind_historical_roles((_share("b"), _share("a")), team="AWAY",
        lineup_status="PROJECTED", active_player_ids={"a", "b"})
    b = bind_historical_roles((_share("a"), _share("b")), team="AWAY",
        lineup_status="PROJECTED", active_player_ids={"a", "b"})
    assert a == b


def test_binding_fails_closed_on_mixed_snapshot():
    with pytest.raises(ValueError, match="one fitted team snapshot"):
        bind_historical_roles((_share("a"), _share("b", digest="b"*64)),
            team="HOME", lineup_status="CONFIRMED", active_player_ids={"a", "b"})


def test_binding_does_not_invent_missing_active_player():
    with pytest.raises(ValueError, match="no eligible historical shares"):
        bind_historical_roles((_share("a"),), team="HOME",
            lineup_status="CONFIRMED", active_player_ids={"missing"})


def test_binding_requires_positive_supported_event_and_shot_weights():
    zero_goal = NHLHistoricalRoleShare(
        player_id="a", team_id="10", cutoff="2026-01-02T00:00:00Z",
        source="nhl@v1", version="role-v1", games=10, shot_weight=2.0,
        goal_weight=0.0, primary_assist_weight=.1, secondary_assist_weight=.1,
        history_sha256="a"*64)
    with pytest.raises(ValueError, match="goal weight"):
        bind_historical_roles((zero_goal,), team="HOME", lineup_status="CONFIRMED",
            active_player_ids={"a"})