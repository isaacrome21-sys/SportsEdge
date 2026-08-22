from sportsedge.ufc_advanced import (
    RoundStats, derive_advanced_features, FightWeekContext, context_uncertainty,
    clv_probability, project_props, prop_truth_gate, validation_slices,
)
from sportsedge.ufc_engine import FighterSnapshot, FightContext


def fighter(name, **kw):
    base=dict(name=name,age=30,height_in=72,reach_in=74,stance='Orthodox',wins=15,losses=4,
              sig_strikes_landed_pm=4.0,sig_strikes_absorbed_pm=3.0,takedowns_per_15=1.5,
              submissions_per_15=0.4,finish_win_rate=0.55,finish_loss_rate=0.25,
              missingness=0.0)
    base.update(kw)
    return FighterSnapshot(**base)


def test_advanced_features_and_context_penalty():
    rounds=[RoundStats(1,300,40,70,30,2,4,90,1,1),RoundStats(2,300,30,60,35,1,3,60,0,0)]
    f=derive_advanced_features(rounds,opponent_strengths=[0.7,0.8])
    assert f.pace_r1 > f.pace_r2
    assert 0 < f.control_share < 1
    assert abs(f.takedown_quality - (3/7)) < 1e-12
    assert context_uncertainty(FightWeekContext(short_notice_days=7,missed_weight=True)) >= 0.13


def test_clv_positive_when_bet_beats_close():
    c=clv_probability(-110,-150,-110)
    assert c['clv'] > 0
    assert c['market_move'] > 0


def test_props_are_separate_and_fail_closed_until_calibrated():
    a=fighter('A',knockdowns_per_15=0.8)
    b=fighter('B',finish_loss_rate=0.45)
    p=project_props(a,b,FightContext(rounds=5))
    assert abs(p.p_gtd+p.p_inside_distance-1.0) < 1e-9
    gate=prop_truth_gate(prob=0.60,odds=+110,market_no_vig=0.50,uncertainty=0.10,calibrated=False)
    assert gate['pass'] is False
    assert gate['reason']=='PROP_NOT_CALIBRATED'


def test_validation_slices_include_year_weight_and_side():
    rows=[
        {'p':0.65,'y':1,'date':'2025-01-01','weight_class':'Lightweight'},
        {'p':0.40,'y':0,'date':'2025-02-01','weight_class':'Welterweight'},
        {'p':0.55,'y':0,'date':'2026-02-01','weight_class':'Lightweight'},
    ]
    names={x.name for x in validation_slices(rows)}
    assert {'all','favorite','underdog','year:2025','year:2026','weight:Lightweight'} <= names
