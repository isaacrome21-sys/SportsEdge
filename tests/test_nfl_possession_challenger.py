import numpy as np
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
        assert xs[-1].outcome=="END_HALF" and xs[-1].points==0

def test_baseline_is_seed_reproducible():
    a=PossessionChallengerBaseline(game_id="g",home_team="H",away_team="A",seed=11).simulate(20)
    b=PossessionChallengerBaseline(game_id="g",home_team="H",away_team="A",seed=11).simulate(20)
    assert a==b

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

def _assert_equivalent(kwargs,n=200_000):
    rm,rt,rp,rc,ro=_reference_arrays(kwargs,n)
    v=VectorizedPossessionChallengerBaseline(**kwargs).simulate(n)
    assert abs(rm.mean()-v.margins.mean()) <= .15
    assert abs(rt.mean()-v.totals.mean()) <= .15
    assert abs(rp.mean()/2-(v.home_possessions+v.away_possessions).mean()/2) <= .05
    assert _ks(rm,v.margins) <= .01
    assert _ks(rt,v.totals) <= .01
    reference_shares=rc.sum(axis=0)/rc.sum()
    vector_shares=v.outcome_counts.sum(axis=0)/v.outcome_counts.sum()
    outcome_diffs=np.abs(reference_shares-vector_shares)
    assert np.all(outcome_diffs <= .003), {
        name:float(diff) for name,diff in zip(VectorizedPossessionChallengerBaseline.OUTCOMES,outcome_diffs)
        if diff>.003
    }
    for k in (3,7):
        d=abs(np.mean(np.abs(rm)==k)-np.mean(np.abs(v.margins)==k))
        if d>.003:
            # Frozen one-time precision retry; tolerance does not move.
            rm2,_,_,_,_=_reference_arrays({**kwargs,"seed":kwargs["seed"]+10000},1_000_000)
            v2=VectorizedPossessionChallengerBaseline(**{**kwargs,"seed":kwargs["seed"]+20000}).simulate(1_000_000)
            d=abs(np.mean(np.abs(rm2)==k)-np.mean(np.abs(v2.margins)==k))
        assert d <= .003
    return {
        "reference_ot_rate":float(np.mean(ro>0)),
        "vector_ot_rate":float(np.mean(v.overtime_possessions>0)),
        "reference_shares":reference_shares,
        "vector_shares":vector_shares,
    }

def test_vector_reference_near_even_high_ot_and_safety_distribution():
    result=_assert_equivalent(dict(seed=4101,td_rate=.10,fg_rate=.08,safety_rate=.01))
    safety_i=list(VectorizedPossessionChallengerBaseline.OUTCOMES).index("SAFETY")
    assert result["reference_ot_rate"] >= .05
    assert result["vector_ot_rate"] >= .05
    assert result["reference_shares"][safety_i] >= .005
    assert result["vector_shares"][safety_i] >= .005

def test_vector_reference_lopsided_home_distribution():
    _assert_equivalent(dict(seed=4201,home_strength=8.0,away_strength=-4.0,strength_scale=100.0,strength_clip=.08))

def test_vector_reference_lopsided_away_distribution():
    _assert_equivalent(dict(seed=4301,home_strength=-5.0,away_strength=7.0,strength_scale=100.0,strength_clip=.08))

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
