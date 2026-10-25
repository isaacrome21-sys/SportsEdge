"""PickRecord must fail closed on non-finite EV/line and unknown selections (#2670 HOLD 6395922592)."""
from __future__ import annotations

import pytest

from sportsedge.pipeline.picks import PickRecord, PickRecordError, expected_value

NAN, INF = float("nan"), float("inf")


def _row(**over):
    row = {
        "sport": "NFL", "market": "total", "selection": "OVER", "line": 47.5,
        "dk_price": -110, "captured_at": "2026-10-25T12:00:00-05:00", "model_p": 0.55,
        "engine": "test", "ev": expected_value(0.55, -110), "ladder_status": "PAPER",
    }
    row.update(over)
    return row


def test_clean_row_round_trips():
    pick = PickRecord.from_dict(_row())
    assert PickRecord.from_dict(pick.to_dict()) == pick


@pytest.mark.parametrize("bad", [NAN, INF, -INF, "0.05", True, None], ids=repr)
def test_bad_ev_rejected(bad):
    with pytest.raises(PickRecordError):
        PickRecord.from_dict(_row(ev=bad))


@pytest.mark.parametrize("bad", [NAN, INF, -INF, "47.5", True], ids=repr)
def test_bad_line_rejected(bad):
    with pytest.raises(PickRecordError):
        PickRecord.from_dict(_row(line=bad))


@pytest.mark.parametrize("bad", ["SIDEWAYS", "over", "Home", " OVER"], ids=repr)
def test_unknown_or_noncanonical_selection_rejected(bad):
    with pytest.raises(PickRecordError):
        PickRecord.from_dict(_row(selection=bad))


@pytest.mark.parametrize("bad", [NAN, INF, True], ids=repr)
def test_bad_model_p_rejected(bad):
    with pytest.raises((PickRecordError, ValueError, OverflowError)):
        PickRecord.from_dict(_row(model_p=bad, ev=0.0))


def test_bad_opposite_price_rejected():
    with pytest.raises(PickRecordError):
        PickRecord.from_dict(_row(opposite_price=50))


def test_moneyline_null_line_still_allowed():
    PickRecord.from_dict(_row(market="moneyline", selection="HOME", line=None))
