"""Research-only NBA live state reconciliation failure cases (no PLAY path)."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.sports.nba.live_status_gate import (
    DKScreenEventReceipt,
    NBAOfficialEventReceipt,
    reconcile_nba_state,
)

NOW = datetime(2026, 10, 22, 2, 0, 0, tzinfo=timezone.utc)
TIP = NOW - timedelta(minutes=15)
NBA_RECEIPT = "a" * 64
DK_RECEIPT = "b" * 64


def receipts():
    official = NBAOfficialEventReceipt(
        event_id="NBA_401", home_team_id="LAL", away_team_id="GSW",
        scheduled_tipoff_utc=TIP, phase="LIVE", period=3,
        clock_seconds_remaining=380,
        source_as_of_utc=NOW - timedelta(seconds=8),
        captured_at_utc=NOW - timedelta(seconds=7),
        provider="NBA_OFFICIAL", evidence_sha256=NBA_RECEIPT,
    )
    sportsbook = DKScreenEventReceipt(
        event_id="NBA_401", home_team_id="LAL", away_team_id="GSW",
        scheduled_tipoff_utc=TIP, phase="LIVE", period=3,
        clock_seconds_remaining=377,
        market_settlement_scope="FULL_GAME_INCLUDING_PRIOR_PLAY",
        source_as_of_utc=NOW - timedelta(seconds=6),
        captured_at_utc=NOW - timedelta(seconds=5),
        bookmaker="DraftKings", evidence_sha256=DK_RECEIPT,
    )
    return official, sportsbook


def reason(official=None, book=None):
    base_o, base_b = receipts()
    return reconcile_nba_state(
        base_o if official is None else official,
        base_b if book is None else book,
        pit_cutoff_utc=NOW,
    )


def test_agreed_live_is_research_only_and_never_betting_authority():
    d = reason()
    assert d.status == "RESEARCH_ONLY_PHASE_RECONCILED"
    assert d.reason_code == "NBA_LIVE_PHASE_AGREEMENT"
    assert d.model_p_authority is False
    assert d.play_authority is False
    assert d.staking_authority is False
    assert not hasattr(d, "model_probability")


def test_agreed_pregame_before_scheduled_tip_is_also_research_only():
    o, b = receipts()
    next_tip = NOW + timedelta(minutes=30)
    d = reason(
        replace(o, phase="PREGAME", scheduled_tipoff_utc=next_tip,
                period=None, clock_seconds_remaining=None),
        replace(b, phase="PREGAME", scheduled_tipoff_utc=next_tip,
                period=None, clock_seconds_remaining=None),
    )
    assert d.status == "RESEARCH_ONLY_PHASE_RECONCILED"
    assert d.play_authority is False


@pytest.mark.parametrize("official_phase,book_phase", [
    ("PREGAME", "LIVE"), ("LIVE", "PREGAME"),
    ("FINAL", "LIVE"), ("LIVE", "UNKNOWN"),
])
def test_independent_status_conflicts_always_refused(official_phase, book_phase):
    o, b = receipts()
    d = reason(replace(o, phase=official_phase), replace(b, phase=book_phase))
    assert (d.status, d.reason_code) == ("REFUSED", "NBA_LIVE_PHASE_CONFLICT")


@pytest.mark.parametrize("field,value", [
    ("event_id", "other_game"), ("home_team_id", "BOS"),
    ("away_team_id", "BOS"),
])
def test_same_game_or_same_teams_mandatory(field, value):
    _, b = receipts()
    d = reason(book=replace(b, **{field: value}))
    assert d.reason_code == "NBA_LIVE_CROSS_EVENT_OR_TEAM_CONFLICT"


def test_book_team_swap_is_not_silent():
    _, b = receipts()
    d = reason(book=replace(b, home_team_id="GSW", away_team_id="LAL"))
    assert d.reason_code == "NBA_LIVE_CROSS_EVENT_OR_TEAM_CONFLICT"


def test_tipoff_identity_conflict_is_refused():
    _, b = receipts()
    d = reason(book=replace(b, scheduled_tipoff_utc=TIP + timedelta(hours=2)))
    assert d.reason_code == "NBA_LIVE_FIXTURE_START_CONFLICT"


@pytest.mark.parametrize("age,expected", [
    (30, "NBA_LIVE_PHASE_AGREEMENT"),
    (31, "NBA_LIVE_OFFICIAL_STALE"),
])
def test_state_frozen_ttl_boundary(age, expected):
    o, _ = receipts()
    d = reason(official=replace(o, source_as_of_utc=NOW - timedelta(seconds=age),
                                captured_at_utc=NOW - timedelta(seconds=age)))
    assert d.reason_code == expected


@pytest.mark.parametrize("age,expected", [
    (20, "NBA_LIVE_PHASE_AGREEMENT"),
    (21, "NBA_LIVE_DK_STALE"),
])
def test_quote_frozen_ttl_boundary(age, expected):
    _, b = receipts()
    d = reason(book=replace(b, source_as_of_utc=NOW - timedelta(seconds=age),
                            captured_at_utc=NOW - timedelta(seconds=age)))
    assert d.reason_code == expected


@pytest.mark.parametrize("field,delta,expected", [
    ("source_as_of_utc", 1, "NBA_LIVE_OFFICIAL_FUTURE_OR_REORDERED_TIMESTAMP"),
    ("captured_at_utc", 1, "NBA_LIVE_OFFICIAL_FUTURE_OR_REORDERED_TIMESTAMP"),
])
def test_future_official_receipt_refused(field, delta, expected):
    o, _ = receipts()
    assert reason(official=replace(o, **{field: NOW + timedelta(seconds=delta)})).reason_code == expected


def test_future_book_receipt_refused():
    _, b = receipts()
    assert reason(book=replace(b, captured_at_utc=NOW + timedelta(seconds=1))).reason_code == "NBA_LIVE_DK_FUTURE_OR_REORDERED_TIMESTAMP"


@pytest.mark.parametrize("field", ["source_as_of_utc", "captured_at_utc"])
def test_naive_time_is_not_interpreted_as_utc(field):
    o, _ = receipts()
    d = reason(official=replace(o, **{field: NOW.replace(tzinfo=None)}))
    assert d.reason_code == "NBA_LIVE_OFFICIAL_TIMESTAMP_INVALID"


@pytest.mark.parametrize("period,clock,expected", [
    (None, 380, "NBA_LIVE_DK_PERIOD_OR_CLOCK_UNVERIFIED"),
    (True, 380, "NBA_LIVE_DK_PERIOD_OR_CLOCK_UNVERIFIED"),
    (3, None, "NBA_LIVE_DK_PERIOD_OR_CLOCK_UNVERIFIED"),
    (3, 900, "NBA_LIVE_DK_PERIOD_OR_CLOCK_UNVERIFIED"),
    (4, 377, "NBA_LIVE_PERIOD_CONFLICT"),
    (3, 190, "NBA_LIVE_GAME_CLOCK_CONFLICT"),
])
def test_period_and_clock_diagnostics(period, clock, expected):
    _, b = receipts()
    d = reason(book=replace(b, period=period, clock_seconds_remaining=clock))
    assert d.reason_code == expected


@pytest.mark.parametrize("scope", [None, "", "FULL_GAME", "UNKNOWN", "QUARTER_3"])
def test_book_live_market_settlement_must_be_explicit(scope):
    _, b = receipts()
    assert reason(book=replace(b, market_settlement_scope=scope)).reason_code == "NBA_LIVE_MARKET_SETTLEMENT_SCOPE_UNVERIFIED"


@pytest.mark.parametrize("phase", ["FINAL", "SUSPENDED", "UNKNOWN"])
def test_mutually_agreed_terminal_or_unknown_is_still_refused(phase):
    o, b = receipts()
    assert reason(replace(o, phase=phase), replace(b, phase=phase)).reason_code == "NBA_LIVE_NONACTIONABLE_PHASE"


def test_pregame_past_scheduled_tip_is_unverified_even_when_sources_agree():
    o, b = receipts()
    d = reason(
        replace(o, phase="PREGAME", period=None, clock_seconds_remaining=None),
        replace(b, phase="PREGAME", period=None, clock_seconds_remaining=None),
    )
    assert d.reason_code == "NBA_LIVE_PREGAME_PAST_SCHEDULED_TIP_UNVERIFIED"


def test_live_before_scheduled_tip_does_not_override_official_time():
    o, b = receipts()
    next_tip = NOW + timedelta(minutes=20)
    assert reason(
        replace(o, scheduled_tipoff_utc=next_tip),
        replace(b, scheduled_tipoff_utc=next_tip),
    ).reason_code == "NBA_LIVE_BEFORE_SCHEDULED_TIP_UNVERIFIED"


def test_distinct_evidence_required_not_self_asserted_duplicate():
    _, b = receipts()
    assert reason(book=replace(b, evidence_sha256=NBA_RECEIPT)).reason_code == "NBA_LIVE_INDEPENDENT_EVIDENCE_REQUIRED"


def test_receipt_provider_labels_are_required_but_not_authenticated():
    o, _ = receipts()
    assert reason(official=replace(o, provider="SCREENSHOT")).reason_code == "NBA_LIVE_SOURCE_PROVENANCE_UNVERIFIED"


def test_invalid_pit_cutoff_fails_closed():
    o, b = receipts()
    d = reconcile_nba_state(o, b, pit_cutoff_utc=NOW.replace(tzinfo=None))
    assert d.reason_code == "NBA_LIVE_PIT_CUTOFF_INVALID"


def test_unhashable_invalid_phase_fails_closed():
    o, _ = receipts()
    assert reason(official=replace(o, phase=[])).reason_code == "NBA_LIVE_UNRECOGNIZED_PHASE"


def test_unhashable_invalid_settlement_fails_closed():
    _, b = receipts()
    assert reason(book=replace(b, market_settlement_scope=[])).reason_code == "NBA_LIVE_MARKET_SETTLEMENT_SCOPE_UNVERIFIED"


def test_official_period_invalid_refused():
    o, _ = receipts()
    assert reason(official=replace(o, period=0)).reason_code == "NBA_LIVE_OFFICIAL_PERIOD_OR_CLOCK_INVALID"


def test_book_source_after_capture_is_refused():
    _, b = receipts()
    assert reason(book=replace(b, source_as_of_utc=NOW - timedelta(seconds=1))).reason_code == "NBA_LIVE_DK_FUTURE_OR_REORDERED_TIMESTAMP"
