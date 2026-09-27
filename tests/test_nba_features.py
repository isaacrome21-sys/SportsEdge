from datetime import datetime, timezone
import pytest

from sportsedge.sports.nba.features import NBAFeatureSnapshot, NBAPlayerRole, NBATeamState


def role(pid="p1", team="H", status="AVAILABLE", mean=32.0, sd=3.0):
    return NBAPlayerRole(pid, team, status, True, mean, sd, 0.25)


def team(tid="H", roles=None):
    return NBATeamState(tid, 99.5, 116.0, 113.0, 1.0, 0.0, tuple(roles or [role(team=tid)]))


def snapshot(captured_hour=18):
    return NBAFeatureSnapshot(
        "g1",
        datetime(2026, 10, 20, 19, tzinfo=timezone.utc),
        datetime(2026, 10, 20, captured_hour, tzinfo=timezone.utc),
        team("H"), team("A", [role("p2", "A")]), "fixture", "v1"
    )


def test_valid_snapshot_is_strictly_pre_tipoff():
    snapshot().validate()


def test_snapshot_rejects_tipoff_or_later_capture():
    with pytest.raises(ValueError, match="PIT violation"):
        snapshot(19).validate()


def test_out_player_must_have_zero_minutes():
    with pytest.raises(ValueError, match="OUT players"):
        role(status="OUT", mean=1.0, sd=0.0).validate()


def test_questionable_players_are_exposed_as_rotation_uncertainty():
    s = NBAFeatureSnapshot(
        "g1", datetime(2026, 10, 20, 19, tzinfo=timezone.utc), datetime(2026, 10, 20, 18, tzinfo=timezone.utc),
        team("H", [role("q", "H", "QUESTIONABLE")]), team("A", [role("a", "A")]), "fixture", "v1"
    )
    s.validate()
    assert s.uncertain_players == ("q",)


def test_team_rejects_duplicate_player_roles():
    with pytest.raises(ValueError, match="unique"):
        team("H", [role("p", "H"), role("p", "H")]).validate()
