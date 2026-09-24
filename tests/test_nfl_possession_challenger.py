import numpy as np
import pytest
import json
import os
from pathlib import Path
from sportsedge.core.simulate.nfl_possession_challenger import (
    Possession, PossessionPath, PossessionChallengerBaseline,
    VectorizedPossessionChallengerBaseline,
)

def test_baseline_alternates_and_flips_halftime():
    s=PossessionChallengerBaseline(game_id="g",home_team="H",away_team="A",seed=7)
    p=s.simulate_one(0)
    assert p.second_half_receiver != p.opening_receiver
    for half in (1,2):
        xs=[x for x in p.possessions if x.half==half]
        assert xs[0].offense == (p.opening_receiver if half==1 else p.second_half_receiver)
        assert all(a.offense!=b.offense for a,b in zip(xs,xs[1:]))
        assert xs[-1].end_seconds==0
        if xs[-1].outcome=="END_HALF":
            assert xs[-1].points==0

def test_baseline_is_seed_reproducible():
    a=PossessionChallengerBaseline(game_id="g",home_team="H",away_team="A",seed=11).simulate(20)
    b=PossessionChallengerBaseline(game_id="g",home_team="H",away_team="A",seed=11).simulate(20)
    assert a==b


class _ScriptedRegulationClock:
    def __init__(self,durations): self.durations=iter(durations)
    def random(self,n=None): return 0.0 if n is None else np.zeros(n)
    def gamma(self,*args,size=None):
        duration=next(self.durations)
        return duration if size is None else np.full(size,duration)


def test_reference_final_regulation_drive_finishing_at_zero_can_score():
    s=PossessionChallengerBaseline(game_id="g",home_team="H",away_team="A",seed=1)
    s.rng=_ScriptedRegulationClock([1800])
    s._outcome=lambda offense:("TD",7)
    half,_=s._half(1,"H",0)
    assert len(half)==1
    assert (half[0].outcome,half[0].points,half[0].end_seconds)==("TD",7,0)


def test_reference_final_regulation_drive_overrun_is_censored():
    s=PossessionChallengerBaseline(game_id="g",home_team="H",away_team="A",seed=1)
    s.rng=_ScriptedRegulationClock([1801])
    s._outcome=lambda offense:("TD",7)
    half,_=s._half(1,"H",0)
    assert len(half)==1
    assert (half[0].outcome,half[0].points,half[0].end_seconds)==("END_HALF",0,0)


def test_vector_final_regulation_drives_finishing_at_zero_can_score():
    s=VectorizedPossessionChallengerBaseline(seed=2)
    s.rng=_ScriptedRegulationClock([1800,1800])
    outcomes=iter([("TD",7),("FG",3)])
    def drive(home):
        outcome,points=next(outcomes)
        index=list(s.OUTCOMES).index(outcome)
        return np.full(len(home),index),np.full(len(home),points,dtype=np.int16)
    s._drive=drive
    v=s.simulate(1)
    assert (int(v.margins[0]),int(v.totals[0]),int(v.overtime_possessions[0]))==(4,10,0)
    assert int(v.outcome_counts[0,0])==1
    assert int(v.outcome_counts[0,1])==1
    assert int(v.outcome_counts[0,6])==0


def _reference_arrays(kwargs,n):
    # Retain numeric summaries only: the frozen million-path precision retry
    # must not keep tens of millions of Possession objects alive.
    simulator=PossessionChallengerBaseline(game_id="g",home_team="H",away_team="A",**kwargs)
    outcome_index={o:i for i,o in enumerate(VectorizedPossessionChallengerBaseline.OUTCOMES)}
    margins=np.empty(n,dtype=np.int32)
    totals=np.empty(n,dtype=np.int32)
    possessions=np.empty(n,dtype=np.int32)
    counts=np.zeros((n,len(outcome_index)),dtype=np.int32)
    ot=np.zeros(n,dtype=np.int32)
    for i in range(n):
        path=simulator.simulate_one(i)
        margins[i]=path.margin
        totals[i]=path.total
        possessions[i]=len(path.possessions)
        for possession in path.possessions:
            counts[i,outcome_index[possession.outcome]]+=1
            if possession.half==3:
                ot[i]+=1
    return margins,totals,possessions,counts,ot


def test_streamed_reference_preserves_materialized_paths_and_rng_order():
    kwargs=dict(seed=4101,td_rate=.10,fg_rate=.08,safety_rate=.10)
    paths=PossessionChallengerBaseline(
        game_id="g",home_team="H",away_team="A",**kwargs
    ).simulate(300)
    margins,totals,possessions,counts,ot=_reference_arrays(kwargs,len(paths))
    np.testing.assert_array_equal(margins,[p.margin for p in paths])
    np.testing.assert_array_equal(totals,[p.total for p in paths])
    np.testing.assert_array_equal(possessions,[len(p.possessions) for p in paths])
    np.testing.assert_array_equal(ot,[sum(q.half==3 for q in p.possessions) for p in paths])
    for j,outcome in enumerate(VectorizedPossessionChallengerBaseline.OUTCOMES):
        np.testing.assert_array_equal(
            counts[:,j],[sum(q.outcome==outcome for q in p.possessions) for p in paths]
        )
    assert np.any(ot>0)
    assert counts[:,5].sum()>0
    np.testing.assert_array_equal(counts.sum(axis=1),possessions)


def test_streamed_reference_does_not_materialize_simulation_batch(monkeypatch):
    def forbidden(*args,**kwargs):
        raise AssertionError("reference summaries must stream simulate_one")
    monkeypatch.setattr(PossessionChallengerBaseline,"simulate",forbidden)
    arrays=_reference_arrays(dict(seed=11),3)
    assert all(len(a)==3 for a in arrays)
    empty=_reference_arrays(dict(seed=11),0)
    assert all(len(a)==0 for a in empty)


def _ks(a,b):
    x=np.sort(np.unique(np.concatenate((a,b))))
    return float(np.max(np.abs(np.searchsorted(np.sort(a),x,side="right")/len(a)-np.searchsorted(np.sort(b),x,side="right")/len(b))))

def _record_equivalence(report):
    print(json.dumps(report,sort_keys=True),flush=True)
    directory=os.environ.get("SPORTSEDGE_EQ_REPORT_DIR")
    if directory:
        path=Path(directory)
        path.mkdir(parents=True,exist_ok=True)
        (path/f"equivalence-{report['reference_seed']}-{report['vector_seed']}.json").write_text(
            json.dumps(report,indent=2,sort_keys=True)+"\n")


def _assert_equivalent(kwargs,vector_seed,n=200_000):
    assert kwargs["seed"] != vector_seed
    rm,rt,rp,rc,ro=_reference_arrays(kwargs,n)
    v=VectorizedPossessionChallengerBaseline(**{**kwargs,"seed":vector_seed}).simulate(n)
    reference_shares=rc.sum(axis=0)/rc.sum()
    vector_shares=v.outcome_counts.sum(axis=0)/v.outcome_counts.sum()
    diffs=np.abs(reference_shares-vector_shares)
    metrics={
        "mean_margin_difference":float(abs(rm.mean()-v.margins.mean())),
        "mean_total_difference":float(abs(rt.mean()-v.totals.mean())),
        "mean_possessions_per_team_difference":float(abs(rp.mean()/2-(v.home_possessions+v.away_possessions).mean()/2)),
        "margin_ks":_ks(rm,v.margins),"total_ks":_ks(rt,v.totals),
        "outcome_share_differences":dict(zip(map(str,VectorizedPossessionChallengerBaseline.OUTCOMES),map(float,diffs))),
        "exact_mass_differences":{str(k):float(abs(np.mean(np.abs(rm)==k)-np.mean(np.abs(v.margins)==k))) for k in (3,7)},
    }
    report={"reference_seed":kwargs["seed"],"vector_seed":vector_seed,
            "parameters":kwargs,"paths_per_implementation":n,"numpy":np.__version__,
            "rng":"PCG64","metrics":metrics,"status":"RUNNING","retry":None,
            "authority":"NONE_SYNTHETIC_MECHANICS_ONLY"}
    _record_equivalence(report)
    try:
        assert metrics["mean_margin_difference"] <= .15
        assert metrics["mean_total_difference"] <= .15
        assert metrics["mean_possessions_per_team_difference"] <= .05
        assert metrics["margin_ks"] <= .01 and metrics["total_ks"] <= .01
        assert np.all(diffs <= .003),metrics["outcome_share_differences"]
        failing=[k for k in (3,7) if metrics["exact_mass_differences"][str(k)]>.003]
        if failing:
            # One fixed precision retry, only for failed exact-mass metrics.
            rs=kwargs["seed"]+10000; vs=vector_seed+20000
            rm2,_,_,_,_=_reference_arrays({**kwargs,"seed":rs},1_000_000)
            v2=VectorizedPossessionChallengerBaseline(**{**kwargs,"seed":vs}).simulate(1_000_000)
            retry_diffs={str(k):float(abs(np.mean(np.abs(rm2)==k)-np.mean(np.abs(v2.margins)==k))) for k in failing}
            report["retry"]={"reference_seed":rs,"vector_seed":vs,"paths_per_implementation":1_000_000,
                             "exact_mass_differences":retry_diffs}
            assert all(d<=.003 for d in retry_diffs.values())
        report["status"]="PASS"
    except BaseException:
        report["status"]="FAIL_OR_INTERRUPTED"
        raise
    finally:
        _record_equivalence(report)
    return {"reference_ot_rate":float(np.mean(ro>0)),
            "vector_ot_rate":float(np.mean(v.overtime_possessions>0)),
            "reference_shares":reference_shares,"vector_shares":vector_shares}


@pytest.mark.parametrize("season,reference_seed,vector_seed",[(2026,4101,5101),(2016,4401,5401),(2024,4501,5501)])
def test_vector_reference_near_even_high_ot_and_safety_distribution(season,reference_seed,vector_seed):
    result=_assert_equivalent(dict(seed=reference_seed,season=season,td_rate=.10,fg_rate=.08,safety_rate=.01),vector_seed)
    safety_i=list(VectorizedPossessionChallengerBaseline.OUTCOMES).index("SAFETY")
    assert result["reference_ot_rate"] >= .05
    assert result["vector_ot_rate"] >= .05
    assert result["reference_shares"][safety_i] >= .005
    assert result["vector_shares"][safety_i] >= .005


def test_vector_reference_lopsided_home_distribution():
    _assert_equivalent(dict(seed=4201,season=2026,home_strength=8.0,away_strength=-4.0,strength_scale=100.0,strength_clip=.08),5201)


def test_vector_reference_lopsided_away_distribution():
    _assert_equivalent(dict(seed=4301,season=2026,home_strength=-5.0,away_strength=7.0,strength_scale=100.0,strength_clip=.08),5301)

def test_reference_safety_points_go_to_defense():
    p=PossessionPath(
        game_id="g",simulation_id=0,home_team="H",away_team="A",
        opening_receiver="H",second_half_receiver="A",
        possessions=(Possession(0,1,"H","A",1800,1700,"SAFETY",-2),),
    )
    assert p.home_score==0
    assert p.away_score==2
    assert p.margin==-2
    assert p.total==2

def test_safety_points_go_to_defense():
    s=VectorizedPossessionChallengerBaseline(seed=44,td_rate=0,fg_rate=0,turnover_rate=0,downs_rate=0,safety_rate=.5)
    v=s.simulate(1000)
    assert np.all(v.totals>=0)
    assert v.outcome_counts[:,5].sum()>0

def test_regulation_ties_enter_ot_and_are_resolved_often():
    s=VectorizedPossessionChallengerBaseline(seed=55,td_rate=.12,fg_rate=.12)
    v=s.simulate(5000)
    assert np.mean(v.overtime_possessions>0) > 0
    assert np.mean(v.margins==0) < .10
