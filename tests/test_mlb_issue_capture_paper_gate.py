"""MLB issue quotes: original capture clock, 180s TTL, PAPER-only display.

All fixtures offline. An issue edit can never rejuvenate an old DK quote.
"""
from datetime import datetime, timedelta

import pytest

from scripts.intake_mlb_lines_issue import (
    _issue_capture_at, _stamp_captured_payload, LinesIntakeError,
)
from scripts.render_mlb_myspari_card import (
    PAPER_ONLY_REASON, paper_only_mlb_rows,
)
from sportsedge.manual_quote_live import partition_live_rows

CT = "-05:00"
POSTED = datetime.fromisoformat("2026-10-25T07:03:00-05:00")


def test_capture_relay_zero_tolerance_and_180_second_boundary():
    capture = _issue_capture_at("2026-10-25T07:00:00-05:00", POSTED)
    assert capture.isoformat() == "2026-10-25T07:00:00-05:00"
    with pytest.raises(LinesIntakeError, match="MLB_CAPTURE_RELAY_TOO_OLD"):
        _issue_capture_at("2026-10-25T06:59:59-05:00", POSTED)
    with pytest.raises(LinesIntakeError, match="MLB_CAPTURE_FUTURE_RELATIVE_TO_ISSUE"):
        _issue_capture_at("2026-10-25T07:03:01-05:00", POSTED)
    with pytest.raises(LinesIntakeError, match="MLB_CAPTURE_TIMESTAMP_REQUIRED"):
        _issue_capture_at(None, POSTED)
    with pytest.raises(LinesIntakeError, match="MLB_CAPTURE_TIMESTAMP_INVALID"):
        _issue_capture_at("last night", POSTED)


def test_capture_provenance_overrides_github_edit_stamp_not_quote():
    captured = _issue_capture_at("2026-10-25T07:01:00-05:00", POSTED)
    payload = {"rows": [
        {"observed_at": POSTED.isoformat(), "timestamp_source": "INTAKE_STAMPED",
         "market_type": "MONEYLINE", "price": 100},
    ]}
    _stamp_captured_payload(payload, captured, POSTED)
    assert payload["captured_at"] == "2026-10-25T07:01:00-05:00"
    assert payload["intake_observed_at"] == POSTED.isoformat()
    assert payload["rows"][0]["observed_at"] == payload["captured_at"]
    assert payload["rows"][0]["timestamp_source"] == "ISSUE_BODY_CAPTURED"
    assert payload["rows"][0]["intake_observed_at"] == POSTED.isoformat()


BASE = {
    "game_id": "Brewers@Rays",
    "market_type": "MONEYLINE",
    "side": "AWAY",
    "line": 0.0,
    "price": 100,
    "paired_side": "HOME",
    "paired_price": -120,
    "book": "draftkings",
    "observed_at": "2026-10-25T10:00:00-05:00",
    "first_pitch_at": "2026-10-25T12:00:00-05:00",
    "source": "MANUAL",
}


def _strict(row, as_of):
    return partition_live_rows(
        [row], run_date="2026-10-25", max_age_minutes=3,
        as_of=datetime.fromisoformat(as_of), enforce_quote_window=True,
    )


def test_strict_card_admits_exact_180_seconds_only():
    live, blocked, _ = _strict(dict(BASE), "2026-10-25T10:03:00-05:00")
    assert len(live) == 1 and blocked == []
    live, blocked, _ = _strict(dict(BASE), "2026-10-25T10:03:01-05:00")
    assert live == [] and blocked[0]["reason"] == "MANUAL_QUOTE_EXPIRED"


def test_strict_card_refuses_future_capture_and_started_game():
    future = dict(BASE, observed_at="2026-10-25T10:04:00-05:00")
    live, blocked, _ = _strict(future, "2026-10-25T10:03:00-05:00")
    assert live == [] and blocked[0]["reason"] == "MANUAL_QUOTE_FROM_FUTURE"
    near_kickoff = dict(BASE, observed_at="2026-10-25T11:59:00-05:00")
    live, blocked, _ = _strict(near_kickoff, "2026-10-25T12:01:00-05:00")
    assert live == [] and blocked[0]["reason"] == "MANUAL_QUOTE_GAME_STARTED"


def test_paper_guard_never_calls_an_unverified_market_actionable():
    original = [
        {"market": "TEAM_TOTAL", "status": "ACTIONABLE",
         "scored_status": "ACTIONABLE", "ev_per_dollar": 0.08},
        {"market": "TOTAL", "status": "PASS", "scored_status": "PASS"},
    ]
    rows = paper_only_mlb_rows(original)
    assert rows[0]["scored_status"] == rows[0]["status"] == "PAPER"
    assert rows[0]["ev_per_dollar"] == 0.08  # diagnostics preserved
    assert PAPER_ONLY_REASON in rows[0]["presentation_reason_codes"]
    assert rows[1]["scored_status"] == "PASS"
    assert original[0]["status"] == "ACTIONABLE"  # pure, nonmutating


def test_strict_card_allows_fresh_quotes_for_tomorrows_bound_fixture():
    tomorrow = dict(BASE, first_pitch_at="2026-10-26T19:00:00-05:00")
    live, blocked, _ = partition_live_rows(
        [tomorrow], run_date=None, max_age_minutes=3,
        as_of=datetime.fromisoformat("2026-10-25T10:01:00-05:00"),
        enforce_quote_window=True,
    )
    assert len(live) == 1 and blocked == []
