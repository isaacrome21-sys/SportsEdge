"""Independent provider kickoff hygiene, without changing the frozen model."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.run_nfl_unified_lines_card import _validate_auto_prop_kickoffs
from sportsedge.nfl_unified_phone import UnifiedNflPhoneError


SCHEDULE = [{
    "game_id": "2026_04_KC_BAL",
    "away_team_id": "KC",
    "home_team_id": "BAL",
    "season": 2026,
    "week": 4,
    "kickoff_ts": "2026-10-04T17:00:00+00:00",
}]


def _ticket(quoted=None):
    game = {"away": "KC", "home": "BAL", "markets": [{"market": "spread"}]}
    if quoted is not None:
        game["commence_time"] = quoted
    return {
        "observed_at": "2026-10-01T19:00:00Z",
        "games": [game],
    }


def test_provider_kickoff_within_seven_minutes_is_admitted():
    _validate_auto_prop_kickoffs(_ticket("2026-10-04T17:07:00Z"), SCHEDULE)


def test_provider_kickoff_one_hour_wrong_fails_closed():
    with pytest.raises(UnifiedNflPhoneError, match="QUOTE_KICKOFF_INDEPENDENT_SCHEDULE_MISMATCH"):
        _validate_auto_prop_kickoffs(_ticket("2026-10-04T18:00:00Z"), SCHEDULE)


def test_naive_provider_kickoff_is_rejected():
    with pytest.raises(UnifiedNflPhoneError, match="quote_kickoff:AWARE_TIMESTAMP_REQUIRED"):
        _validate_auto_prop_kickoffs(_ticket("2026-10-04T17:00:00"), SCHEDULE)


def test_invalid_or_ambiguous_schedule_never_admits_quote():
    with pytest.raises(UnifiedNflPhoneError, match="SCHEDULE_MATCH_REQUIRED"):
        _validate_auto_prop_kickoffs(_ticket("2026-10-04T17:00:00Z"), [])
    with pytest.raises(UnifiedNflPhoneError, match="SCHEDULE_MATCH_REQUIRED"):
        _validate_auto_prop_kickoffs(_ticket("2026-10-04T17:00:00Z"), SCHEDULE * 2)


def test_manual_ticket_without_event_clock_keeps_legacy_binding():
    _validate_auto_prop_kickoffs(_ticket(), SCHEDULE)


def test_multiple_games_bad_second_event_fails_entire_ticket():
    ticket = _ticket("2026-10-04T17:00:00Z")
    ticket["games"].append({
        "away": "KC", "home": "BAL",
        "commence_time": "2026-10-04T19:00:00Z",
        "markets": [],
    })
    with pytest.raises(UnifiedNflPhoneError, match="QUOTE_KICKOFF_INDEPENDENT_SCHEDULE_MISMATCH"):
        _validate_auto_prop_kickoffs(ticket, SCHEDULE)


def test_auto_phone_status_distinguishes_bad_quote_from_model_outage():
    from scripts.run_auto_dk_cards import _nfl_prop_failure_status
    assert _nfl_prop_failure_status("QUOTE_KICKOFF_INDEPENDENT_SCHEDULE_MISMATCH:KC@BAL") == "QUOTE_EVENT_REJECTED"
    assert _nfl_prop_failure_status("quote_kickoff:AWARE_TIMESTAMP_REQUIRED") == "QUOTE_EVENT_REJECTED"
    assert _nfl_prop_failure_status("PIT_NFLVERSE_HISTORY_REQUIRED") == "MODEL_UNAVAILABLE"
