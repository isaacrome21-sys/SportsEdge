"""Do not let file order select one of conflicting closing quotes."""
from itertools import permutations
import pytest
from sportsedge.forward_validation import ForwardValidationRefusal, evaluate_family
from test_forward_validation_20261020 import base_cfg, close, outcome, row


def test_conflicting_close_records_refused_in_either_input_order():
    quotes = [close(over=-200, under=180), close(over=180, under=-200)]
    for ordered in permutations(quotes):
        with pytest.raises(ForwardValidationRefusal) as exc:
            evaluate_family(base_cfg(), [row()], list(ordered), [outcome()])
        assert exc.value.reason == 'CLOSE_DUPLICATE'


@pytest.mark.parametrize('line', [10.5, '10.5'])
def test_even_identical_close_records_need_one_explicit_final_record(line):
    with pytest.raises(ForwardValidationRefusal) as exc:
        evaluate_family(base_cfg(), [row()], [close(), close(line=line)], [outcome()])
    assert exc.value.reason == 'CLOSE_DUPLICATE'


def test_multiple_capture_times_are_not_silently_resolved_by_input_order():
    quotes = [close(at='2026-11-01T17:10:00-05:00'), close(at='2026-11-01T17:50:00-05:00')]
    with pytest.raises(ForwardValidationRefusal) as exc:
        evaluate_family(base_cfg(), [row()], quotes, [outcome()])
    assert exc.value.reason == 'CLOSE_DUPLICATE'


def test_different_subjects_and_lines_remain_distinct():
    result = evaluate_family(base_cfg(), [row()],
                             [close(), close(subject='P2'), close(line=11.5)], [outcome()])
    assert result['markets']['SYNTH']['rows'][0]['close_status'] == 'READABLE'
