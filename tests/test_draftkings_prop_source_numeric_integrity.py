"""Direct DK research quotes must fail closed on corrupt numeric provider values."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sportsedge.draftkings_prop_source import (
    DraftKingsPropSourceError,
    _american_from_decimal,
    _line,
    _selection_price,
    parse_category_payload,
)


@pytest.mark.parametrize("odds", [True, False, 0, -50, 99, "-99", "+99", "NaN", "inf", float("inf"), float("nan"), 110.5])
def test_invalid_american_odds_are_never_truncated_or_admitted(odds) -> None:
    with pytest.raises(DraftKingsPropSourceError, match="DK_ODDS_INVALID"):
        _selection_price({"displayOdds": odds})


@pytest.mark.parametrize("odds,expected", [("−110", -110), ("+154", 154), (-198, -198), (100.0, 100)])
def test_valid_american_quotes_preserved_without_converting_market_math(odds, expected) -> None:
    assert _selection_price({"displayOdds": odds}) == expected


def test_invalid_preferred_odds_cannot_be_silently_replaced_by_secondary_value() -> None:
    with pytest.raises(DraftKingsPropSourceError, match="DK_ODDS_INVALID"):
        _selection_price({"displayOdds": {"american": 0, "americanOdds": -110}})


@pytest.mark.parametrize("odds", [True, False, float("nan"), float("inf"), 1, 0, -2, "not-a-number"])
def test_decimal_odds_conversion_rejects_invalid_numbers(odds) -> None:
    with pytest.raises(DraftKingsPropSourceError, match="DK_ODDS_INVALID"):
        _american_from_decimal(odds)


@pytest.mark.parametrize("line", [True, float("nan"), float("inf"), -0.5, "not-a-number"])
def test_invalid_count_market_lines_are_refused(line) -> None:
    with pytest.raises(DraftKingsPropSourceError, match="DK_LINE_INVALID"):
        _line({"points": line}, "OVER")


def test_malformed_provider_quote_is_logged_as_failure_and_never_emitted() -> None:
    snapshot = parse_category_payload({
        "markets": [{"id": "market1", "name": "Hits"}],
        "selections": [
            {"marketId": "market1", "eventId": "event1", "participantName": "Sample Hitter",
             "label": "Over 1.5", "points": 1.5, "displayOdds": -110},
            {"marketId": "market1", "eventId": "event1", "participantName": "Sample Hitter",
             "label": "Under 1.5", "points": float("nan"), "displayOdds": -110},
            {"marketId": "market1", "eventId": "event1", "participantName": "Sample Hitter",
             "label": "Under 1.5", "points": 1.5, "displayOdds": 0},
        ],
    }, retrieved_at=datetime(2026, 10, 25, tzinfo=timezone.utc))
    assert len(snapshot.quotes) == 1
    assert snapshot.quotes[0]["american_odds"] == -110
    assert snapshot.quotes[0]["line"] == 1.5
    assert len(snapshot.failures) == 2
    assert any("DK_LINE_INVALID" in item["reason"] for item in snapshot.failures)
    assert any("DK_ODDS_INVALID" in item["reason"] for item in snapshot.failures)
