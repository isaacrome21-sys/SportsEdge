from datetime import datetime,timedelta,timezone
import pytest
from sportsedge.sports.nba.period_history import NBAPeriodObservation,fit_period_parameters,period_history_digest
UTC=timezone.utc

def obs(i,home,away,delay=3):
    tip=datetime(2025,1,i,1,tzinfo=UTC)
    return NBAPeriodObservation(str(i),tip,tip+timedelta(hours=delay),home,away,"provider","box-v1")

def test_period_fit_uses_only_observed_history_and_is_deterministic():
    a=obs(1,(20,30,25,25),(20,30,25,25))
    b=obs(2,(30,20,25,25),(30,20,25,25))
    future=obs(3,(40,10,10,40),(40,10,10,40),delay=72)
    asof=datetime(2025,1,4,tzinfo=UTC)
    p=fit_period_parameters([future,b,a],as_of=asof)
    assert p.quarter_shares == (.25,.25,.25,.25)
    assert p.version.endswith(period_history_digest([a,b])[:12])

def test_period_fit_rejects_pregame_observation():
    a=obs(1,(20,30,25,25),(20,30,25,25))
    bad=NBAPeriodObservation(a.game_id,a.tipoff,a.tipoff,a.home_quarters,a.away_quarters,a.source,a.source_version)
    with pytest.raises(ValueError,match="observed after tipoff"):
        bad.validate()

def test_period_fit_requires_support_in_every_quarter():
    a=obs(1,(20,0,25,25),(20,0,25,25))
    with pytest.raises(ValueError,match="each quarter"):
        fit_period_parameters([a],as_of=datetime(2025,1,2,tzinfo=UTC))
