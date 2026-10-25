"""Experimental NBA CLV must never compare an entry against itself.

These are synthetic timestamps/prices only, not sportsbook receipts or graded
forward bets.
"""
from __future__ import annotations

import pytest

from sportsedge.sports.nba.clv_ledger import (
    capture_rows, closing_quote, pick_row, settle,
)
from sportsedge.sports.nba.lines_card import parse_lines


TIP = "2026-10-24T23:30:00Z"
ENTRY = "2026-10-24T17:00:00-05:00"
EARLIER = "2026-10-24T16:00:00-05:00"
LATER = "2026-10-24T18:20:00-05:00"
POST = "2026-10-24T19:00:00-05:00"


def capture(at, *, ml="+150 -180", source="DK_ISSUE"):
    body = (
        f"Lakers @ Celtics\nCaptured: {at}\n"
        f"ML {ml}\nSpread -4.5 -110 -110\nTotal 221.5 -110 -110\n"
    )
    return capture_rows(parse_lines(body), game_date="2026-10-24", source=source)


def pick(at=ENTRY):
    return pick_row(capture(at)[0], model_p=0.45, engine_id="synthetic-test")


@pytest.mark.parametrize("snapshots,reason", [
    ("entry_only", "CLOSE_NOT_AFTER_ENTRY"),
    ("earlier_only", "CLOSE_NOT_AFTER_ENTRY"),
    ("same_clock_changed_price", "CLOSE_NOT_AFTER_ENTRY"),
    ("posttip_only_after_entry", "CLOSE_NOT_AFTER_ENTRY"),
    ("only_posttip", "CLOSE_NOT_PRETIP"),
])
def test_no_independent_later_pretip_snapshot_no_clv(snapshots, reason):
    entry = capture(ENTRY)
    variants = {
        "entry_only": entry,
        "earlier_only": capture(EARLIER),
        "same_clock_changed_price": capture(ENTRY, ml="+140 -165"),
        "posttip_only_after_entry": entry + capture(POST),
        "only_posttip": capture(POST),
    }
    p = pick()
    close, actual = closing_quote(p, variants[snapshots], tip_utc=TIP)
    assert close is None and actual == reason
    settled = settle(p, variants[snapshots], tip_utc=TIP)
    assert settled["close_reason"] == reason
    assert "clv_prob" not in settled and "close_american" not in settled


@pytest.mark.parametrize("bad_entry", [TIP, POST])
def test_at_or_after_tip_entry_refused_even_with_pretip_candidate(bad_entry):
    p = pick(bad_entry)
    close, reason = closing_quote(p, capture(LATER), tip_utc=TIP)
    assert close is None and reason == "ENTRY_NOT_PRETIP"


def test_valid_separate_later_pretip_snapshot_keeps_clv():
    p = pick()
    close, reason = closing_quote(
        p, capture(EARLIER) + capture(ENTRY) + capture(LATER, ml="+130 -155"),
        tip_utc=TIP,
    )
    assert reason == "OK" and close["american"] == 130
    settled = settle(p, capture(LATER, ml="+130 -155"), tip_utc=TIP)
    assert settled["close_reason"] == "OK"
    assert "clv_prob" in settled


def test_other_provider_cannot_supply_missing_dk_close():
    p = pick()
    other = capture(LATER, ml="+130 -155", source="OTHER_BOOK")
    close, reason = closing_quote(p, other, tip_utc=TIP)
    assert close is None and reason == "NO_CLOSE_ROW"


def test_missing_entry_source_cannot_claim_close():
    p = pick()
    del p["source"]
    close, reason = closing_quote(p, capture(LATER), tip_utc=TIP)
    assert close is None and reason == "ENTRY_SOURCE_MISSING"
