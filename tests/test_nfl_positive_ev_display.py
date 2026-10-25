import pytest
from scripts.render_nfl_myspari_card import render


def card(ev, **updates):
    row = dict(market='total',line=42.5,residual_mode=True,
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
