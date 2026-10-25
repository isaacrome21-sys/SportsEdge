import pytest
from scripts.render_nfl_myspari_card import render


def card(ev, **updates):
    row = dict(market='total',line=42.5,residual_mode=True,
        quote_retrieved_at='2026-10-25T09:32:21-05:00',
        away_or_over_price=-112,home_or_under_price=-108,
        residual_research_prices=[dict(selection='OVER',price_american=-112,
                                      ev_per_dollar=ev)])
    row.update(updates)
    return render({'games':[{'away':'NYG','home':'HOU','markets':[row]}]})


@pytest.mark.parametrize('ev',[.0001,.003,.004,.02])
def test_any_positive_estimate_shown_with_selected_price(ev):
    text=card(ev)
    assert 'POSITIVE EV — PAPER' in text
    assert 'OVER @ -112' in text
    assert 'NOT proven, not a bet' in text


@pytest.mark.parametrize('ev',[0,-.001])
def test_nonpositive_not_labeled_positive(ev):
    assert 'POSITIVE EV — PAPER' not in card(ev)


def test_model_warning_preserved():
    assert 'too few past games' in card(.004,lean_block='NO_LEAN:THIN_CALIBRATION')


def test_stale_refusal_not_bypassed():
    assert 'POSITIVE EV — PAPER' not in card(.004,no_model='STALE_QUOTE')


def test_original_quote_time_is_displayed():
    assert 'Captured: 2026-10-25T09:32:21-05:00' in card(.004,quote_retrieved_at='2026-10-25T09:32:21-05:00')

def test_missing_capture_is_not_invented():
    assert 'POSITIVE EV — PAPER' not in card(.004,quote_retrieved_at=None)
    assert 'capture time required' in card(.004,quote_retrieved_at=None)

def test_tiny_positive_not_rounded_to_zero():
    assert 'estimated EV +1e-06%' in card(.00000001)


@pytest.mark.parametrize('stamp',['invalid','2026-10-25T09:32:21',''])
def test_malformed_or_naive_capture_withholds_positive_candidate(stamp):
    assert 'POSITIVE EV — PAPER' not in card(.004,quote_retrieved_at=stamp)


@pytest.mark.parametrize('ev',[float('nan'),float('inf'),float('-inf')])
def test_nonfinite_estimate_never_reaches_candidate_card(ev):
    text=card(ev)
    assert 'POSITIVE EV — PAPER' not in text
    assert 'POSITIVE EV — PAPER' not in text


@pytest.mark.parametrize('ev',['bad',{},[],True,None,10**1000])
def test_malformed_ev_does_not_crash_card(ev):
    assert 'POSITIVE EV — PAPER' not in card(ev)

@pytest.mark.parametrize('price',[None,True,-112.5,float('inf'),'bad',0])
def test_invalid_selected_price_is_withheld(price):
    choice=dict(selection='OVER',ev_per_dollar=.004,price_american=price)
    assert 'POSITIVE EV — PAPER' not in card(.004,lean=choice)

def test_valid_choice_survives_malformed_opposite():
    choices=[dict(selection='OVER',ev_per_dollar='bad',price_american=-112),
             dict(selection='UNDER',ev_per_dollar=.003,price_american=-108)]
    text=card(.004,residual_research_prices=choices)
    assert 'UNDER @ -108' in text
