"""Synthetic quote-age admission regressions; never sportsbook evidence."""
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.research_three_sport_bridge import (
    RESEARCH_AGED_QUOTE,
    ResearchQuoteError,
    _bridge_quote_status,
    price_three_sport_research,
)

NOW = datetime(2026, 10, 25, 20, 0, tzinfo=timezone.utc)


def stamp(age):
    return (NOW - timedelta(seconds=age)).isoformat()


@pytest.mark.parametrize("age,expected", [
    (0, "RECENT_CAPTURED_QUOTE"),
    (150, "RECENT_CAPTURED_QUOTE"),
    (150.001, RESEARCH_AGED_QUOTE),
    (180, RESEARCH_AGED_QUOTE),
    (300, RESEARCH_AGED_QUOTE),
])
def test_quote_age_boundary(age, expected):
    assert _bridge_quote_status(stamp(age), now=NOW) == expected


@pytest.mark.parametrize("age", [300.001, 301, 3600])
def test_quote_older_than_300_seconds_refused(age):
    with pytest.raises(ResearchQuoteError, match="QUOTE_OVER_300S_REFUSED"):
        _bridge_quote_status(stamp(age), now=NOW)


def model():
    return {
        "sport": "NFL", "game_id": "SYNTHETIC_GAME", "market": "TOTAL",
        "line": 42.5, "selection": "OVER", "estimate_p": 0.55,
        "push_p": 0.0, "status": "PRICED_RESEARCH", "market_blind": True,
        "model_source": "SYNTHETIC_TEST_ONLY", "as_of_utc": NOW.isoformat(),
        "kickoff_utc": (NOW + timedelta(hours=1)).isoformat(),
        "phase": "PREGAME", "validated_vs_close": False,
        "official_authority": False, "staking_authority": False,
    }


def paired(ages):
    return [
        {"sport": "NFL", "game_id": "SYNTHETIC_GAME", "market": "TOTAL",
         "line": 42.5, "selection": side, "odds": -110,
         "book": "draftkings", "quote_captured_at": stamp(age)}
        for side, age in zip(("OVER", "UNDER"), ages)
    ]


def priced(ages):
    return price_three_sport_research([model()], paired(ages),
                                      as_of=NOW.isoformat())["rows"][0]


def test_recent_two_sided_quote_remains_research_only():
    row = priced((150, 150))
    assert row["quote_status"] == "RECENT_CAPTURED_QUOTE"
    assert row["research_only"] is True
    assert row["staking_authority"] is False


def test_mixed_aged_pair_cannot_be_fresh_or_staked():
    row = priced((149, 151))
    assert row["quote_status"] == "STALE_QUOTE"
    assert row["quote_age_class"] == RESEARCH_AGED_QUOTE
    assert row["status"] == "WATCH_QUOTE_NOT_CURRENT"
    assert row["staking_authority"] is False


def test_aged_pair_at_300_is_research_watch_only():
    row = priced((300, 300))
    assert row["quote_status"] == "STALE_QUOTE"
    assert row["quote_age_class"] == RESEARCH_AGED_QUOTE
    assert row["status"] == "WATCH_QUOTE_NOT_CURRENT"
    assert row["staking_authority"] is False


def test_over_300_pair_refuses_pricing_before_ev():
    row = priced((300.001, 300.001))
    assert row["status"] == "WATCH_QUOTE_NOT_CURRENT"
    assert row["quote_status"] == "STALE_QUOTE"
    assert row["quote_age_class"] == "QUOTE_OVER_300S_REFUSED"
    assert row["quote_refused"] is True
    assert "QUOTE_OVER_300S_REFUSED" in row["reason"]
    assert "ev_per_dollar" not in row
    assert row["staking_authority"] is False


def test_missing_quote_clock_cannot_be_current():
    assert _bridge_quote_status(None, now=NOW) == "UNVERIFIED_QUOTE_FRESHNESS"


def test_aged_single_side_validated_prop_retains_legacy_watch_with_age_flag():
    prop = {**model(), "market": "PLAYER_RECEIVING_YARDS",
            "player_id": "synthetic-player", "line": 49.5}
    quote = {**paired((151,))[0], "market": "PLAYER_RECEIVING_YARDS",
             "player_id": "synthetic-player", "line": 49.5}
    row = price_three_sport_research(
        [prop], [quote], as_of=NOW.isoformat(),
        validation_resolver=lambda *_: {"validation_status": "VALIDATED"})["rows"][0]
    assert row["status"] == "WATCH_QUOTE_NOT_CURRENT"
    assert row["quote_status"] == "STALE_QUOTE"
    assert row["quote_age_class"] == RESEARCH_AGED_QUOTE
    assert row["staking_authority"] is False


def test_over_300_single_side_refused_without_model_ev():
    prop = {**model(), "market": "PLAYER_RECEIVING_YARDS",
            "player_id": "synthetic-player", "line": 49.5}
    quote = {**paired((301,))[0], "market": "PLAYER_RECEIVING_YARDS",
             "player_id": "synthetic-player", "line": 49.5}
    row = price_three_sport_research(
        [prop], [quote], as_of=NOW.isoformat(),
        validation_resolver=lambda *_: {"validation_status": "VALIDATED"})["rows"][0]
    assert row["status"] == "WATCH_QUOTE_NOT_CURRENT"
    assert row["quote_refused"] is True
    assert row["quote_age_class"] == "QUOTE_OVER_300S_REFUSED"
    assert "ev_per_dollar" not in row
    assert "model_probability" not in row


@pytest.mark.parametrize("future_seconds", [0.001, 1, 120])
def test_future_dated_quote_refused_before_research_ev(future_seconds):
    with pytest.raises(ResearchQuoteError, match="QUOTE_TIMESTAMP_IN_FUTURE_REFUSED"):
        _bridge_quote_status(stamp(-future_seconds), now=NOW)


def test_one_future_side_refuses_entire_paired_quote_without_ev():
    row = priced((0, -0.001))
    assert row["status"] == "WATCH_QUOTE_NOT_CURRENT"
    assert row["quote_status"] == "STALE_QUOTE"
    assert row["quote_age_class"] == "QUOTE_TIMESTAMP_IN_FUTURE_REFUSED"
    assert row["quote_refused"] is True
    assert row["staking_authority"] is False
    for field in ("ev_per_dollar", "model_probability", "dk_no_vig_p", "edge_pp"):
        assert field not in row


def test_future_single_side_prop_refuses_even_with_validated_family():
    prop = {**model(), "market": "PLAYER_RECEIVING_YARDS",
            "player_id": "synthetic-player", "line": 49.5}
    quote = {**paired((-0.001,))[0], "market": "PLAYER_RECEIVING_YARDS",
             "player_id": "synthetic-player", "line": 49.5}
    row = price_three_sport_research(
        [prop], [quote], as_of=NOW.isoformat(),
        validation_resolver=lambda *_: {"validation_status": "VALIDATED"})["rows"][0]
    assert row["status"] == "WATCH_QUOTE_NOT_CURRENT"
    assert row["quote_refused"] is True
    assert row["quote_age_class"] == "QUOTE_TIMESTAMP_IN_FUTURE_REFUSED"
    assert row["staking_authority"] is False
    for field in ("ev_per_dollar", "model_probability", "dk_no_vig_p", "edge_pp"):
        assert field not in row
