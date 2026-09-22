from datetime import datetime, timedelta, timezone
import pytest
from sportsedge.sports.nhl.features import GoalieState, TeamSnapshot, NHLFeatureSnapshot


def team(team_id):
    return TeamSnapshot(team_id, 3.0, 2.8, 31.0, 29.0, 6.5, 6.0, 1.0, 200.0, 0.1)


def goalie(goalie_id, status="CONFIRMED"):
    return GoalieState(goalie_id, status, .91, .12, 500)


def snap(captured_delta=-1, away_status="CONFIRMED"):
    puck = datetime(2026, 10, 10, 0, tzinfo=timezone.utc)
    return NHLFeatureSnapshot("g1", puck, puck + timedelta(hours=captured_delta), team("H"), team("A"), goalie("hg"), goalie("ag", away_status), "fixture", "v1")


def test_snapshot_requires_strictly_pregame_capture():
    snap().validate()
    with pytest.raises(ValueError, match="PIT violation"):
        snap(captured_delta=0).validate()


def test_goalie_certainty_tracks_projected_starter():
    assert snap().goalie_certainty == "CONFIRMED"
    assert snap(away_status="PROJECTED").goalie_certainty == "PROJECTED"


def test_unknown_goalie_status_fails_closed():
    with pytest.raises(ValueError, match="status"):
        snap(away_status="LIKELY").validate()
