"""Direct shared-pricer boundary attacks, independent of upstream guards."""
import math
import pytest
from sportsedge.market_coverage import finalize_research_row


def row(**changes):
    args = dict(sport='CFB', game='A @ B', selection='OVER', market='TOTAL',
                price=-110, dec=1 + 100 / 110, line=50.5, win=.6, push=0.,
                home_mean=25., away_mean=25., kickoff_iso='2026-10-28T00:00:00Z',
                context={}, context_notes=[], model_family='test')
    return finalize_research_row(**(args | changes))


@pytest.mark.parametrize('field', ['win', 'push', 'dec', 'price', 'line', 'home_mean', 'away_mean', 'min_ev'])
@pytest.mark.parametrize('value', [math.nan, math.inf, -math.inf, True, '0.6', None])
def test_invalid_numbers_cannot_become_edges(field, value):
    if field == 'line' and value is None:
        assert row(line=None)['line'] is None  # Moneylines have no threshold.
    else:
        with pytest.raises(ValueError, match='RESEARCH_ROW_INVALID_NUMBER'):
            row(**{field: value})


@pytest.mark.parametrize('win,push', [(0, 0), (1, 0), (-.1, 0), (1.1, 0), (.8, .8), (.6, -.1), (1, 0)])
def test_invalid_probability_mass_is_rejected(win, push):
    with pytest.raises(ValueError, match='PROBABILITY_MASS'):
        row(win=win, push=push)


@pytest.mark.parametrize('field,value', [('official_authority', True), ('staking_authority', True),
    ('model_p_authority', True), ('research_only', False), ('status', 'VERIFIED'),
    ('estimate_p', .99), ('ev_per_dollar', 10), ('model_validation', 'PASSED')])
def test_metadata_cannot_override_authority_or_pricing(field, value):
    with pytest.raises(ValueError, match='RESERVED_FIELDS'):
        row(extra={field: value})


def test_valid_push_ev_and_provenance_are_preserved():
    result = row(win=.5, push=.1, extra={'distribution_sha256': 'abc'})
    assert result['loss_p'] == .4
    assert result['ev_per_dollar'] == pytest.approx(.5 * (100 / 110) - .4, abs=1e-6)
    assert result['distribution_sha256'] == 'abc'
    assert result['official_authority'] is False


@pytest.mark.parametrize('win', [1e-9, 1e-7, 0.9999999])
def test_finite_interior_probabilities_survive_without_rounding_gate(win):
    result = row(win=win)
    assert result['research_only'] is True
    assert result['official_authority'] is False
    assert 0 < result['estimate_p'] < 1


@pytest.mark.parametrize('price,dec', [(-110, 2.0), (150, 1.5), (-110, 1.909)])
def test_mismatched_decimal_and_american_odds_refused(price, dec):
    with pytest.raises(ValueError, match='RESEARCH_ROW_INVALID_ODDS'):
        row(price=price, dec=dec)


def test_positive_american_odds_matching_decimal_accepted():
    assert row(price=150, dec=2.5)['odds_american'] == 150


@pytest.mark.parametrize('min_ev', [-1, -1e-9, .1500001, 1])
def test_finalizer_refuses_unsupported_ev_thresholds(min_ev):
    with pytest.raises(ValueError, match='RESEARCH_ROW_INVALID_MIN_EV'):
        row(win=.4, min_ev=min_ev)


def test_direct_finalizer_cannot_label_negative_ev_as_edge():
    result = row(win=.4, min_ev=0)
    assert result['ev_per_dollar'] < 0
    assert result['status'] == 'BELOW_THRESHOLD'
