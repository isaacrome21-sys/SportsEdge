"""Reject invalid numeric evidence before scoring or CLV arithmetic."""
import pytest
from sportsedge.forward_validation import ForwardValidationRefusal, evaluate_family
from test_forward_validation_20261020 import base_cfg, close, outcome, row, yes_cfg, yes_row


@pytest.mark.parametrize('form', ['TWO_SIDED', 'YES_ONLY'])
@pytest.mark.parametrize('bad', [float('inf'), float('-inf'), float('nan'), True, 0, 'bad', 10**400])
def test_invalid_entry_odds_refused(form, bad):
    cfg, entry = base_cfg(), row()
    if form == 'YES_ONLY':
        cfg = yes_cfg()
        entry = yes_row('y1', 'E1', 'P1', p_yes=.6, yes_price=bad)
    else:
        entry['entry_prices']['OVER'] = bad
    with pytest.raises(ForwardValidationRefusal) as exc:
        evaluate_family(cfg, [entry], [], [])
    assert exc.value.reason == 'PRICE_INVALID'


@pytest.mark.parametrize('bad', [float('inf'), float('-inf'), float('nan'), True, 0, 'bad', 10**400])
def test_invalid_matched_close_odds_refused(bad):
    with pytest.raises(ForwardValidationRefusal) as exc:
        evaluate_family(base_cfg(), [row()], [close(over=bad)], [outcome()])
    assert exc.value.reason == 'PRICE_INVALID'


@pytest.mark.parametrize('bad', ['bad', True, [], {}, 10**400])
def test_invalid_probability_refused_by_name(bad):
    entry = row()
    entry['model_p']['OVER'] = bad
    with pytest.raises(ForwardValidationRefusal) as exc:
        evaluate_family(base_cfg(), [entry], [], [])
    assert exc.value.reason == 'MODEL_PROBABILITY_INVALID'


@pytest.mark.parametrize('field', ['model_p', 'entry_prices'])
@pytest.mark.parametrize('bad', [True, [1], 'bad'])
def test_invalid_probability_or_price_container_refused(field, bad):
    entry = row()
    entry[field] = bad
    with pytest.raises(ForwardValidationRefusal) as exc:
        evaluate_family(base_cfg(), [entry], [], [])
    assert exc.value.reason == ('PRICE_INVALID' if field == 'entry_prices' else 'MODEL_PROBABILITY_INVALID')


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), float('-inf'), True, None, 'bad', 10**400])
@pytest.mark.parametrize('location', ['entry', 'close'])
def test_invalid_line_cannot_be_graded_as_push_or_loss(bad, location):
    entry, quote = row(), close()
    (entry if location == 'entry' else quote)['line'] = bad
    with pytest.raises(ForwardValidationRefusal) as exc:
        evaluate_family(base_cfg(), [entry], [quote], [outcome()])
    assert exc.value.reason == 'LINE_INVALID'


def test_valid_numeric_strings_keep_existing_scoring():
    baseline = evaluate_family(base_cfg(), [row()], [close()], [outcome()])
    entry, quote = row(), close()
    entry['model_p'] = {k: str(v) for k,v in entry['model_p'].items()}
    entry['entry_prices'] = {k: str(v) for k,v in entry['entry_prices'].items()}
    quote['prices'] = {k: str(v) for k,v in quote['prices'].items()}
    actual = evaluate_family(base_cfg(), [entry], [quote], [outcome()])
    for field in ('verdict', 'clv', 'win_loss', 'logloss_model', 'logloss_market_entry'):
        assert actual['markets']['SYNTH'][field] == baseline['markets']['SYNTH'][field]


def test_equivalent_numeric_line_cannot_duplicate_a_prospective_row():
    duplicate = row(row_id='r2', line='10.5')
    with pytest.raises(ForwardValidationRefusal) as exc:
        evaluate_family(base_cfg(), [row(), duplicate], [], [])
    assert exc.value.reason == 'DUPLICATE_PROSPECTIVE_ROW'


@pytest.mark.parametrize('bad', [[], False, '', 'bad', [100]])
def test_malformed_close_price_container_refused(bad):
    quote = close()
    quote['prices'] = bad
    with pytest.raises(ForwardValidationRefusal) as exc:
        evaluate_family(base_cfg(), [row()], [quote], [outcome()])
    assert exc.value.reason == 'PRICE_INVALID'
