"""Ambiguous clocks must never produce forward-validation evidence."""
import pytest

from sportsedge.forward_validation import ForwardValidationRefusal, evaluate_family
from test_forward_validation_20261020 import base_cfg, close, outcome, row


@pytest.mark.parametrize("field", ["event_start", "recorded_at", "entry_captured_at"])
@pytest.mark.parametrize("bad", ["2026-11-01T12:00:00", "2026-11-01", "not-a-time"])
def test_ambiguous_entry_clock_is_named_refusal(field, bad):
    entry = row()
    entry[field] = bad
    with pytest.raises(ForwardValidationRefusal) as exc:
        evaluate_family(base_cfg(), [entry], [close()], [outcome()])
    assert exc.value.reason == "RECORD_MISSING_TIMESTAMP"
    assert exc.value.detail["field"] == field


def test_all_naive_clocks_cannot_be_scored_as_prospective():
    entry = row()
    for field in ("event_start", "recorded_at", "entry_captured_at"):
        entry[field] = entry[field][:-6]
    with pytest.raises(ForwardValidationRefusal):
        evaluate_family(base_cfg(), [entry], [close(at="2026-11-01T17:30:00")], [outcome()])


@pytest.mark.parametrize("bad", ["2026-11-01T17:30:00", "2026-11-01", "not-a-time"])
@pytest.mark.parametrize("unmatched", [False, True])
def test_every_close_clock_is_validated_before_indexing(bad, unmatched):
    quote = close(event="UNMATCHED" if unmatched else "E1", at=bad)
    with pytest.raises(ForwardValidationRefusal) as exc:
        evaluate_family(base_cfg(), [row()], [quote], [outcome()])
    assert exc.value.reason == "CLOSE_RECORD_MISSING_TIMESTAMP"


def test_equivalent_offset_instants_have_identical_scoring():
    local = evaluate_family(base_cfg(), [row()], [close()], [outcome()])
    utc_row = row(start="2026-11-01T23:00:00Z", entry_at="2026-11-01T17:00:00Z",
                  recorded_at="2026-11-01T17:00:30Z")
    utc = evaluate_family(base_cfg(), [utc_row], [close(at="2026-11-01T22:30:00Z")], [outcome()])
    for key in ("verdict", "gates", "clv", "win_loss", "logloss_model", "logloss_market_entry"):
        assert local["markets"]["SYNTH"][key] == utc["markets"]["SYNTH"][key]
