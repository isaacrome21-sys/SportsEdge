"""Synthetic adversarial tests only; no invented authentic quotes or results."""
from __future__ import annotations

import pytest
from sportsedge.postgame_ledger_audit import audit

BASE = {
    "sport": "NFL", "event_id": "fixture-event", "selection_id": "fixture-selection",
    "market": "spread", "model_version": "fixture-v1", "line": 3.5,
    "captured_at": "2026-10-25T12:00:00-05:00",
    "event_start": "2026-10-25T13:00:00-05:00",
    "close_captured_at": "2026-10-25T12:59:00-05:00",
    "status": "WIN", "american_odds": -110, "entry_opposite_american_odds": -110,
    "close_american_odds": -115, "close_opposite_american_odds": -105,
    "sportsbook": "DK", "close_sportsbook": "DK", "capture_span_seconds": 150,
    "stake": 1, "wager_type": "STRAIGHT",
}


def row(**changes):
    return {**BASE, **changes}


def test_complete_metadata_never_verifies_itself():
    result = audit([row()])
    assert result["settled_rows"] == 1
    assert result["quote_evidence_tiers"] == {"READY_FOR_INDEPENDENT_REVIEW": 1}
    assert result["verified_picks"] == result["play_units_authorized"] == 0
    assert result["authority"] == "RESEARCH_AUDIT_ONLY_NOT_VERIFIED"


@pytest.mark.parametrize("span,tier,reason", [
    (0, "READY_FOR_INDEPENDENT_REVIEW", None),
    (150, "READY_FOR_INDEPENDENT_REVIEW", None),
    (150.0001, "RESEARCH", "CAPTURE_SPAN_150_TO_300_RESEARCH"),
    (300, "RESEARCH", "CAPTURE_SPAN_150_TO_300_RESEARCH"),
    (300.0001, "REFUSED", "CAPTURE_SPAN_OUT_OF_RANGE"),
    (-1, "REFUSED", "CAPTURE_SPAN_OUT_OF_RANGE"),
    ("NaN", "REFUSED", "CAPTURE_SPAN_OUT_OF_RANGE"),
])
def test_capture_span_boundaries(span, tier, reason):
    result = audit([row(capture_span_seconds=span)])
    assert result["quote_evidence_tiers"] == {tier: 1}
    if reason:
        assert result["findings"][0]["code"] == reason
    else:
        assert not result["findings"]


@pytest.mark.parametrize("updates,reason", [
    ({"close_captured_at": "2026-10-25T12:00:00-05:00"}, "CLOSE_NOT_SEPARATE_LATER_PREGAME"),
    ({"close_captured_at": "2026-10-25T13:00:00-05:00"}, "CLOSE_NOT_SEPARATE_LATER_PREGAME"),
    ({"close_captured_at": "2026-10-25T12:59:00"}, "CLOSE_PAIR_OR_TIME_INVALID"),
    ({"close_captured_at": None}, "PAIRED_ENTRY_OR_CLOSE_MISSING"),
    ({"close_american_odds": None}, "PAIRED_ENTRY_OR_CLOSE_MISSING"),
    ({"close_opposite_american_odds": None}, "PAIRED_ENTRY_OR_CLOSE_MISSING"),
    ({"entry_opposite_american_odds": None}, "PAIRED_ENTRY_OR_CLOSE_MISSING"),
    ({"close_american_odds": -99}, "CLOSE_PAIR_OR_TIME_INVALID"),
    ({"close_sportsbook": "OTHER"}, "DK_CLOSE_SOURCE_NOT_ATTESTED"),
    ({"sportsbook": "OTHER"}, "DK_SOURCE_NOT_ATTESTED"),
])
def test_pair_and_source_fail_closed(updates, reason):
    result = audit([row(**updates)])
    assert result["quote_evidence_tiers"].get("READY_FOR_INDEPENDENT_REVIEW", 0) == 0
    assert result["findings"][0]["code"] == reason


@pytest.mark.parametrize("updates", [
    {"captured_at": "2026-10-25T13:00:00-05:00"},
    {"captured_at": "2026-10-25T12:00:00"},
    {"captured_at": "not-a-time"},
    {"american_odds": -99},
    {"american_odds": "-110.5"},
    {"american_odds": "NaN"},
    {"stake": "NaN"},
    {"stake": 0},
    {"stake": True},
])
def test_invalid_settlement_row_never_enters_profit(updates):
    result = audit([row(**updates)])
    assert result["settled_rows"] == 0
    assert result["settlement_profit_units"] == "0"


def test_invalid_first_row_does_not_poison_later_valid_identity():
    result = audit([row(american_odds="-110.5"), row()])
    assert result["settled_rows"] == 1
    assert [x["code"] for x in result["findings"]] == ["INVALID_PRICE_OR_PREGAME_TIME"]


def test_pending_first_row_does_not_poison_later_valid_identity():
    result = audit([row(status="PENDING"), row()])
    assert result["settled_rows"] == 1
    assert [x["code"] for x in result["findings"]] == ["UNSETTLED_OR_UNKNOWN"]


def test_duplicate_valid_identity_refused():
    result = audit([row(), row()])
    assert result["settled_rows"] == 1
    assert result["findings"][0]["code"] == "DUPLICATE_SELECTION"


def test_alternate_line_is_distinct_identity():
    result = audit([row(), row(line=4.5)])
    assert result["settled_rows"] == 2


@pytest.mark.parametrize("sport", ["MLB", "NFL", "CFB", "NBA", "NHL", "CBB"])
def test_six_sports_explicit(sport):
    result = audit([row(sport=sport)])
    assert result["settled_rows"] == 1


def test_unknown_sport_refused():
    result = audit([row(sport="PGA")])
    assert result["settled_rows"] == 0
    assert result["findings"][0]["code"] == "UNKNOWN_SPORT"


@pytest.mark.parametrize("status,expected", [
    ("WIN", "0.9090909090909090909090909091"),
    ("LOSS", "-1"), ("PUSH", "0"), ("VOID", "0"),
])
def test_profit_math(status, expected):
    result = audit([row(status=status)])
    assert result["settlement_profit_units"] == expected


def test_price_cap_is_evidence_hold_not_retroactive_settlement_change():
    result = audit([row(american_odds=-166)])
    assert result["settled_rows"] == 1
    assert result["quote_evidence_tiers"] == {"RESEARCH": 1}
    assert result["findings"][0]["code"] == "STRAIGHT_PRICE_BELOW_MINUS_165_CAP"


def test_illinois_college_refused_from_evidence_when_explicitly_flagged():
    result = audit([row(sport="CBB", illinois_college=True)])
    assert result["quote_evidence_tiers"] == {"REFUSED": 1}
    assert result["findings"][0]["code"] == "ILLINOIS_COLLEGE_EXCLUDED"


def test_missing_span_is_research_only():
    data = row()
    del data["capture_span_seconds"]
    result = audit([data])
    assert result["quote_evidence_tiers"] == {"RESEARCH": 1}
    assert result["findings"][0]["code"] == "CAPTURE_SPAN_MISSING_OR_INVALID"


@pytest.mark.parametrize("updates,reason", [
    ({"event_id": ["unhashable"]}, "INVALID_IDENTITY"),
    ({"market": {"bad": 1}}, "INVALID_IDENTITY"),
    ({"line": [1, 2]}, "INVALID_IDENTITY"),
    ({"sport": ["NFL"]}, "UNKNOWN_SPORT"),
    ({"american_odds": ["-110"]}, "INVALID_PRICE_OR_PREGAME_TIME"),
    ({"stake": {"bad": 1}}, "INVALID_PRICE_OR_PREGAME_TIME"),
])
def test_malformed_untrusted_row_does_not_abort_batch(updates, reason):
    result = audit([row(**updates), row()])
    assert result["settled_rows"] == 1
    assert result["findings"][0]["code"] == reason


def test_boolean_capture_span_refused():
    result = audit([row(capture_span_seconds=True)])
    assert result["quote_evidence_tiers"] == {"REFUSED": 1}
    assert result["findings"][0]["code"] == "CAPTURE_SPAN_OUT_OF_RANGE"
