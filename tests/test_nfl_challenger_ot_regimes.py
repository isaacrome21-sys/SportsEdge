import numpy as np
import pytest
from sportsedge.core.simulate.nfl_challenger_ot_rules import regular_season_ot_rules
from sportsedge.core.simulate.nfl_possession_challenger import (
    PossessionChallengerBaseline, VectorizedPossessionChallengerBaseline,
)


class ScriptedClock:
    def __init__(self,durations): self.durations=iter(durations)
    def random(self,n=None): return 0.0 if n is None else np.zeros(n)
    def gamma(self,*args,size=None):
        duration=next(self.durations)
        return duration if size is None else np.full(size,duration)


@pytest.mark.parametrize("season,seconds,opening_td",[(2016,900,True),(2017,600,True),(2024,600,True),(2025,600,False),(2026,600,False)])
def test_season_regime_binding(season,seconds,opening_td):
    rules=regular_season_ot_rules(season)
    assert (rules.period_seconds,rules.opening_td_ends_game)==(seconds,opening_td)


@pytest.mark.parametrize("season",[2015,2027,None,True,2025.5,"2026"])
def test_unsupported_regime_fails_closed(season):
    with pytest.raises(ValueError,match="REGIME_UNSUPPORTED"):
        regular_season_ot_rules(season)


@pytest.mark.parametrize("season,events,durations,expected",[
    (2016,[("TD",7)],[100],(6,0,1,800)),
    (2024,[("TD",8)],[100],(6,0,1,500)),
    (2026,[("TD",7),("TD",8)],[100,100],(7,8,2,400)),
    (2025,[("TD",7),("TD",7),("FG",3)],[100,100,100],(10,7,3,300)),
    (2024,[("FG",3),("FG",3),("PUNT",0),("FG",3)],[100]*4,(3,6,4,200)),
    (2026,[("PUNT",0),("TD",8)],[100,100],(0,6,2,400)),
    (2026,[("FG",3),("TD",7)],[100,100],(3,6,2,400)),
    (2026,[("SAFETY",-2)],[100],(0,2,1,500)),
    (2016,[("SAFETY",-2)],[100],(0,2,1,800)),
    (2026,[("TD",7)],[600],(7,0,1,0)),
    (2026,[],[601],(0,0,1,0)),
    (2026,[("FG",3)],[500,101],(3,0,2,0)),
    (2026,[("FG",3),("FG",3)],[300,300],(3,3,2,0)),
    (2016,[("PUNT",0)]*13+[("FG",3)],[1]*14,(0,3,14,886)),
])
def test_reference_and_vector_ot_against_scripted_rule_oracle(season,events,durations,expected):
    reference=PossessionChallengerBaseline(game_id="g",home_team="H",away_team="A",seed=1,season=season)
    reference.rng=ScriptedClock(durations)
    outcomes=iter(events)
    reference._outcome=lambda offense: next(outcomes)
    path=reference._overtime("H",0)
    scores=reference._scores(path)
    assert (*scores,len(path),path[-1].end_seconds)==expected
    assert all(p.end_seconds>=0 and p.start_seconds>p.end_seconds for p in path)
    assert all(a.end_seconds==b.start_seconds for a,b in zip(path,path[1:]))

    vector=VectorizedPossessionChallengerBaseline(seed=2,season=season)
    vector.rng=ScriptedClock(durations)
    # The vector draws even on truncated drives; that draw is explicitly ignored.
    outcomes=iter(events)
    def drive(home):
        outcome,points=next(outcomes,("PUNT",0))
        index=list(vector.OUTCOMES).index(outcome)
        return np.full(len(home),index),np.full(len(home),points,dtype=np.int16)
    vector._drive=drive
    hs,aw,hp,ap,ot=(np.zeros(1,dtype=np.int16) for _ in range(5))
    counts=np.zeros((1,7),dtype=np.int16)
    vector._overtime(hs,aw,hp,ap,counts,ot)
    assert (int(hs[0]),int(aw[0]),int(ot[0]))==expected[:3]
    assert int(hp[0]+ap[0])==len(path)
    for j,outcome in enumerate(vector.OUTCOMES):
        assert counts[0,j]==sum(p.outcome==outcome for p in path)
