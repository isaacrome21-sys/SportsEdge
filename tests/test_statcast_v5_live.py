import pytest

from sportsedge.statcast_v5_data import RollingContact, V5State
from sportsedge.statcast_v5_live import StatcastV5LiveError, assemble_live_statcast_features, resolved_top3


def _filled(n=100,x=.4,barrels=10,hard=40,ev=90.0):
    return RollingContact(n=n,sum_xhit=n*.3,sum_xvalue=n*x,barrels=barrels,hard_hits=hard,sum_ev=n*ev,ev_n=n)


def test_resolved_top3_requires_exact_primary_slots():
    rows=[{"player_id":11,"slot":1,"sequence":0},{"player_id":12,"slot":2,"sequence":0},{"player_id":13,"slot":3,"sequence":0},{"player_id":99,"slot":1,"sequence":1}]
    assert resolved_top3(rows)==(11,12,13)
    with pytest.raises(StatcastV5LiveError,match="TOP3_LINEUP_UNRESOLVED"):
        resolved_top3(rows[:2])


def test_live_features_use_exact_contract_order_and_opposing_starter():
    state=V5State()
    state.team["A"]=_filled(x=.41); state.team["H"]=_filled(x=.43)
    state.pitcher[800]=_filled(n=60,x=.35); state.pitcher[900]=_filled(n=60,x=.37)
    for pid,x in ((11,.31),(12,.32),(13,.33),(21,.34),(22,.35),(23,.36)):
        state.batter[pid]=_filled(n=30,x=x)
    got=assemble_live_statcast_features(state,away_team="A",home_team="H",away_starter_id=800,home_starter_id=900,away_top3=(11,12,13),home_top3=(21,22,23))
    assert got["away"]["off_xwoba"]==pytest.approx(.41)
    assert got["away"]["opp_sp_xwoba_allowed"]==pytest.approx(.37)
    assert got["home"]["opp_sp_xwoba_allowed"]==pytest.approx(.35)
    assert got["first_inning"]["away_sp_xwoba_allowed"]==pytest.approx(.35)
    assert got["first_inning"]["home_sp_xwoba_allowed"]==pytest.approx(.37)


def test_live_features_fail_on_insufficient_starter_history():
    state=V5State(); state.team["A"]=_filled(); state.team["H"]=_filled(); state.pitcher[800]=_filled(n=60); state.pitcher[900]=_filled(n=2)
    for pid in (11,12,13,21,22,23): state.batter[pid]=_filled(n=30)
    with pytest.raises(StatcastV5LiveError,match="PITCHER_PRIOR_EVIDENCE_INSUFFICIENT"):
        assemble_live_statcast_features(state,away_team="A",home_team="H",away_starter_id=800,home_starter_id=900,away_top3=(11,12,13),home_top3=(21,22,23))
