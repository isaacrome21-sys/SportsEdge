from datetime import datetime, timedelta, timezone
import pytest
from sportsedge.sports.nba.availability import NBAAvailabilitySnapshot
from sportsedge.sports.nba.player_history import NBAPlayerBoxObservation
from sportsedge.sports.nba.rotation import bind_availability_roles

ASOF=datetime(2026,9,24,18,tzinfo=timezone.utc)
def box(pid="p1"):
    return NBAPlayerBoxObservation("g0",pid,"T",ASOF-timedelta(days=2),ASOF-timedelta(days=2)+timedelta(hours=3),30,15,6,5,2,100,"BOX","v1")
def av(status, pid="p1", delta=1):
    return NBAAvailabilitySnapshot(pid,"T",status,ASOF-timedelta(hours=delta),"INJ","v1")

def test_available_role_uses_pit_history_and_binds_digest():
    b=bind_availability_roles([box()],[av("AVAILABLE")],player_teams={"p1":"HOME"},as_of=ASOF)
    assert b.roles[0].minutes_mean == 30
    assert len(b.availability_sha256)==64 and b.version.startswith("NBA_AVAILABILITY_BOUND_ROLES_V1:")

def test_out_zeroes_minutes_without_inventing_availability_probability():
    b=bind_availability_roles([box()],[av("OUT")],player_teams={"p1":"HOME"},as_of=ASOF)
    assert (b.roles[0].minutes_mean,b.roles[0].minutes_sd)==(0.0,0.0)

def test_uncertain_status_requires_explicit_minutes_scenario():
    with pytest.raises(ValueError,match="explicit minutes scenario"):
        bind_availability_roles([box()],[av("QUESTIONABLE")],player_teams={"p1":"HOME"},as_of=ASOF)
    b=bind_availability_roles([box()],[av("QUESTIONABLE")],player_teams={"p1":"HOME"},as_of=ASOF,uncertain_minutes={"p1":(24,5)})
    assert (b.roles[0].minutes_mean,b.roles[0].minutes_sd)==(24,5)

def test_future_availability_and_missing_player_fail_closed():
    with pytest.raises(ValueError,match="no PIT-eligible"):
        bind_availability_roles([box()],[NBAAvailabilitySnapshot("p1","T","AVAILABLE",ASOF+timedelta(minutes=1),"INJ","v1")],player_teams={"p1":"HOME"},as_of=ASOF)
    with pytest.raises(ValueError,match="no PIT-eligible"):
        bind_availability_roles([box()],[av("AVAILABLE")],player_teams={"p2":"AWAY"},as_of=ASOF)

def test_override_rejected_for_certain_status():
    with pytest.raises(ValueError,match="only allowed"):
        bind_availability_roles([box()],[av("AVAILABLE")],player_teams={"p1":"HOME"},as_of=ASOF,uncertain_minutes={"p1":(20,4)})
