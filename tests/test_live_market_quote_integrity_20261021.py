"""Fail-closed quote validation before a live market may be marked paired-ready."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.live_markets import LiveMarketError, LiveMarketQuote, quote_gaps


NOW = datetime(2026, 10, 21, 21, 10, tzinfo=timezone.utc)


def _quote(**updates):
    base = LiveMarketQuote(
        sport="NFL", event_id="event-1", book="DK", market="TOTAL",
        contract_key="FULL_GAME_TOTAL_45.5",
        focal_selection="OVER 45.5", opposite_selection="UNDER 45.5",
        focal_odds=-110, opposite_odds=-110,
        source_as_of=NOW - timedelta(seconds=2), retrieved_at=NOW,
        active=True, provider="CAPTURED",
    )
    return replace(base, **updates)


def test_exact_valid_pair_and_genuine_one_sided_gap():
    assert _quote().governance_status == "PAIRED_QUOTE_READY"
    gap = _quote(opposite_odds=None)
    assert gap.governance_status == "LIVE_QUOTE_DATA_GAP"
    assert quote_gaps([_quote(), gap]) == [gap]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"),
                                  True, False, 99, -99, 0, "-110", object()])
@pytest.mark.parametrize("field", ["focal_odds", "opposite_odds"])
def test_bad_american_odds_cannot_be_paired_ready(field, bad):
    with pytest.raises(LiveMarketError, match="invalid American odds"):
        _quote(**{field: bad}).governance_status


@pytest.mark.parametrize("bad", ["", "   ", None, 123])
@pytest.mark.parametrize("field", ["event_id", "book", "contract_key",
                                   "focal_selection", "opposite_selection", "provider"])
def test_bad_identity_cannot_be_paired_ready(field, bad):
    with pytest.raises(LiveMarketError, match="identity/provenance"):
        _quote(**{field: bad}).governance_status


def test_same_selection_on_both_sides_refused_even_with_different_case_or_padding():
    with pytest.raises(LiveMarketError, match="opposing selections"):
        _quote(opposite_selection=" over 45.5 ").governance_status


@pytest.mark.parametrize("field", ["source_as_of", "retrieved_at"])
@pytest.mark.parametrize("bad", [NOW.replace(tzinfo=None), None, "2026-10-21T21:10:00Z"])
def test_bad_or_naive_timestamps_refused(field, bad):
    with pytest.raises(LiveMarketError, match="timezone-aware"):
        _quote(**{field: bad}).governance_status


def test_future_source_timestamp_refused():
    with pytest.raises(LiveMarketError, match="source_as_of cannot be after"):
        _quote(source_as_of=NOW + timedelta(microseconds=1)).governance_status


def test_plus_and_minus_100_are_valid_moneyline_odds():
    assert _quote(focal_odds=100, opposite_odds=-100).governance_status == "PAIRED_QUOTE_READY"
