from sportsedge.game_risk_guard import apply_game_risk_guard


def row(*, market, selection, odds, edge, ev, p=.55, kelly=.03, game='1', status='OFFICIAL_BET'):
    return {
        'game_id':game,
        'market':market,
        'selection':selection,
        'american_odds':odds,
        'edge':edge,
        'ev_per_dollar':ev,
        'model_p':p,
        'kelly_fraction':kelly,
        'bet_status':status,
    }


def by_market(rows):
    return {r['market']:r for r in rows}


def test_heavy_dog_moneyline_and_linked_runline_are_blocked():
    rows=apply_game_risk_guard([
        row(market='MONEYLINE',selection='Kansas City Royals',odds=201,edge=.0879,ev=.2646,p=.4201),
        row(market='RUN_LINE',selection='Kansas City Royals',odds=-111,edge=.0668,ev=.1270,p=.5929),
        row(market='MONEYLINE',selection='Los Angeles Dodgers',odds=-217,edge=-.10,ev=-.15,p=.58,status='PASS'),
    ])
    m=by_market(rows)
    assert m['MONEYLINE']['bet_status']=='PASS'
    assert m['MONEYLINE']['risk_gate_reason']=='HEAVY_DOG_SIDE_UNVALIDATED'
    assert m['RUN_LINE']['bet_status']=='PASS'
    assert m['RUN_LINE']['risk_gate_reason']=='HEAVY_DOG_SIDE_UNVALIDATED'


def test_moderate_dog_requires_real_buffer_and_caps_kelly():
    rows=apply_game_risk_guard([
        row(market='MONEYLINE',selection='Dog',odds=140,edge=.060,ev=.14,p=.48,kelly=.05),
    ])
    r=rows[0]
    assert r['bet_status']=='OFFICIAL_BET'
    assert r['risk_gate_reason']=='UNDERDOG_BUFFER_MET'
    assert r['kelly_fraction']==.015


def test_moderate_dog_with_small_edge_is_pass():
    rows=apply_game_risk_guard([
        row(market='MONEYLINE',selection='Dog',odds=125,edge=.035,ev=.08,p=.48),
    ])
    assert rows[0]['bet_status']=='PASS'
    assert rows[0]['risk_gate_reason']=='UNDERDOG_EDGE_BUFFER_NOT_MET'


def test_large_dog_model_market_disagreement_is_not_treated_as_free_edge():
    rows=apply_game_risk_guard([
        row(market='MONEYLINE',selection='Dog',odds=150,edge=.09,ev=.20,p=.49),
    ])
    assert rows[0]['bet_status']=='PASS'
    assert rows[0]['risk_gate_reason']=='UNDERDOG_MARKET_DISAGREEMENT_UNVALIDATED'


def test_correlated_moderate_dog_side_exposure_prefers_runline_only():
    rows=apply_game_risk_guard([
        row(market='MONEYLINE',selection='Dog',odds=145,edge=.060,ev=.15,p=.47),
        row(market='RUN_LINE',selection='Dog',odds=-125,edge=.055,ev=.11,p=.61),
    ])
    m=by_market(rows)
    assert m['MONEYLINE']['bet_status']=='PASS'
    assert m['MONEYLINE']['risk_gate_reason']=='CORRELATED_SIDE_EXPOSURE_SUPPRESSED'
    assert m['RUN_LINE']['bet_status']=='OFFICIAL_BET'
    assert 'GAME_SIDE_EXPOSURE_SELECTED' in m['RUN_LINE']['risk_gate_reason']


def test_favorite_side_exposure_prefers_moneyline_only():
    rows=apply_game_risk_guard([
        row(market='MONEYLINE',selection='Favorite',odds=-145,edge=.045,ev=.07,p=.63),
        row(market='RUN_LINE',selection='Favorite',odds=135,edge=.050,ev=.12,p=.48),
    ])
    m=by_market(rows)
    assert m['MONEYLINE']['bet_status']=='OFFICIAL_BET'
    assert m['RUN_LINE']['bet_status']=='PASS'
    assert m['RUN_LINE']['risk_gate_reason']=='CORRELATED_SIDE_EXPOSURE_SUPPRESSED'


def test_runline_without_underlying_moneyline_fails_closed():
    rows=apply_game_risk_guard([
        row(market='RUN_LINE',selection='Unknown Side',odds=-110,edge=.07,ev=.13,p=.60),
    ])
    assert rows[0]['bet_status']=='PASS'
    assert rows[0]['risk_gate_reason']=='UNDERLYING_ML_PRICE_MISSING_FOR_SIDE_RISK'


def test_nonofficial_rows_pass_through_without_promotion():
    rows=apply_game_risk_guard([
        row(market='MONEYLINE',selection='Dog',odds=220,edge=.10,ev=.30,p=.45,status='PASS'),
    ])
    assert rows[0]['bet_status']=='PASS'
    assert rows[0]['pre_risk_gate_status']=='PASS'
