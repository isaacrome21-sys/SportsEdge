"""Hostile-boundary regression tests for the forward-validation evaluator.

Reproductions from the Oct 27, 2026 adversarial pass over
``sportsedge/forward_validation/core.py``: zoneless timestamps crashed
with a raw TypeError (or were silently admitted when the whole file was
naive); model probabilities and entry prices were coerced through
float() (strings scored, ``True`` became decimal 1.01, an in-band -50
became 3.0); a string line evaded DUPLICATE_PROSPECTIVE_ROW and scored
as a second sample row; a NaN line silently scored as a push; and two
close records for one key silently overwrote in list order, so a stale
capture could become "the close" CLV is computed from. Every case must
now end in a named ForwardValidationRefusal.
"""
import pytest

from sportsedge.forward_validation import core
from sportsedge.forward_validation.core import ForwardValidationRefusal
from sportsedge.forward_validation.nba_props import load_nba_config

CFG = load_nba_config("player_points", version="V1")
START = "2026-10-28T19:00:00-05:00"


def _row(**kw):
    base = {"row_id": "r1", "event_id": "e1", "subject_id": "p1",
            "market": "player_points", "line": 24.5,
            "model_version": CFG.model_version,
            "model_p": {"OVER": 0.55, "UNDER": 0.45},
            "entry_prices": {"OVER": -110, "UNDER": -110},
            "entry_captured_at": "2026-10-28T18:00:00-05:00",
            "event_start": START,
            "recorded_at": "2026-10-28T18:05:00-05:00"}
    base.update(kw)
    return base


def _close(**kw):
    base = {"event_id": "e1", "subject_id": "p1", "market": "player_points",
            "line": 24.5, "prices": {"OVER": -115, "UNDER": -105},
            "captured_at": "2026-10-28T18:50:00-05:00"}
    base.update(kw)
    return base


OUT = [{"event_id": "e1", "subject_id": "p1", "market": "player_points",
        "value": 30}]


def _ev(rows, closes=None, outcomes=None):
    return core.evaluate_family(
        CFG, rows, [_close()] if closes is None else closes,
        OUT if outcomes is None else outcomes)


def _refuses(reason, rows, closes=None, outcomes=None):
    with pytest.raises(ForwardValidationRefusal) as ei:
        _ev(rows, closes, outcomes)
    assert ei.value.reason == reason


def test_control_valid_row_scores():
    record = _ev([_row()])
    assert record["markets"]["player_points"]["graded_rows"] == 1


@pytest.mark.parametrize("field", ["recorded_at", "event_start",
                                   "entry_captured_at"])
def test_zoneless_row_timestamp_refused(field):
    _refuses("RECORD_MISSING_TIMESTAMP",
             [_row(**{field: "2026-10-28T18:05:00"})])


def test_zoneless_close_timestamp_refused():
    _refuses("RECORD_MISSING_TIMESTAMP", [_row()],
             closes=[_close(captured_at="2026-10-28T18:50:00")])


@pytest.mark.parametrize("mp", [{"OVER": "0.55", "UNDER": "0.45"},
                                {"OVER": "abc", "UNDER": 0.45},
                                {"OVER": True, "UNDER": 0.45},
                                {"OVER": float("nan"), "UNDER": 0.45},
                                [0.55, 0.45], "probs"])
def test_model_probability_wrong_types_refused(mp):
    _refuses("MODEL_PROBABILITY_INVALID", [_row(model_p=mp)])


@pytest.mark.parametrize("price", ["-110", True, -50, 0, float("inf"), None])
def test_entry_price_wrong_types_refused(price):
    _refuses("PRICE_INVALID",
             [_row(entry_prices={"OVER": price, "UNDER": -110})])


def test_entry_prices_non_mapping_refused():
    _refuses("PRICE_INVALID", [_row(entry_prices=[-110, -110])])


def test_duplicate_row_cannot_evade_via_string_line():
    _refuses("ROW_LINE_INVALID", [_row(), _row(row_id="r2", line="24.5")])


@pytest.mark.parametrize("line", ["abc", None, float("nan"), float("inf"), True])
def test_line_wrong_types_refused(line):
    _refuses("ROW_LINE_INVALID", [_row(line=line)])


def test_non_dict_row_refused():
    _refuses("ROW_RECORD_INVALID", ["junk"])


def test_row_missing_event_id_refused():
    row = _row()
    del row["event_id"]
    _refuses("ROW_RECORD_INVALID", [row])


def test_duplicate_close_records_refused():
    _refuses("CLOSE_DUPLICATE", [_row()],
             closes=[_close(), _close(captured_at="2026-10-28T18:55:00-05:00")])


@pytest.mark.parametrize("bad", ["junk", {"line": "abc", "captured_at": "2026-10-28T18:50:00-05:00",
                                          "event_id": "e1", "market": "player_points"}])
def test_close_record_malformed_refused(bad):
    with pytest.raises(ForwardValidationRefusal) as ei:
        _ev([_row()], closes=[bad])
    assert ei.value.reason in ("CLOSE_RECORD_INVALID", "CLOSE_DUPLICATE",
                               "CLOSE_RECORD_MISSING_TIMESTAMP")


def test_int_and_float_line_forms_share_the_duplicate_key():
    _refuses("DUPLICATE_PROSPECTIVE_ROW",
             [_row(line=24), _row(row_id="r2", line=24.0)],
             outcomes=[{"event_id": "e1", "subject_id": "p1",
                        "market": "player_points", "value": 30}])
