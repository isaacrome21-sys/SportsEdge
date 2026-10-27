"""Adversarial checks for shared, research-only market data admission."""

from datetime import datetime, timezone

import pytest

from sportsedge.both_side_pricing import attach_sibling_quotes, complement_model_p
from sportsedge.market_data_contract import (
    MarketDataContractError,
    MarketQuote,
    PublicBettingSplit,
)
from sportsedge.the_odds_api_live import TheOddsApiError, normalize_response


NOW = datetime(2026, 10, 26, 20, 0, tzinfo=timezone.utc)


def _quote(**overrides):
    base = dict(
        provider="THE_ODDS_API", book="draftkings", sport_key="americanfootball_nfl",
        provider_event_id="g", market="totals", selection="Over",
        american_odds=-110, captured_at=NOW, provider_updated_at=NOW,
        raw_payload_sha256="a" * 64, point=42.5,
    )
    base.update(overrides)
    return MarketQuote(**base)


@pytest.mark.parametrize("odds", [-110.5, -110.0, True, False, -99, 0, 99, float("inf"), float("nan"), "-110"])
def test_market_quote_refuses_noninteger_or_nonamerican_odds(odds):
    with pytest.raises(MarketDataContractError, match="AMERICAN_ODDS_INVALID"):
        _quote(american_odds=odds)


@pytest.mark.parametrize("point", [float("nan"), float("inf"), -float("inf"), True, "nonsense"])
def test_market_quote_refuses_invalid_spread_or_total_point(point):
    with pytest.raises(MarketDataContractError, match="POINT_INVALID"):
        _quote(point=point)


@pytest.mark.parametrize("sha", ["z" * 64, "a" * 63, "a" * 65, None])
def test_market_quote_rejects_non_sha256_receipt(sha):
    with pytest.raises(MarketDataContractError, match="RAW_PAYLOAD_SHA256_INVALID"):
        _quote(raw_payload_sha256=sha)


def _provider_payload(price, point=42.5):
    return [{
        "id": "g", "sport_key": "americanfootball_nfl",
        "commence_time": "2026-10-26T21:00:00Z",
        "bookmakers": [{"key": "draftkings", "last_update": "2026-10-26T19:59:00Z",
                        "markets": [{"key": "totals", "outcomes": [{"name": "Over", "price": price, "point": point}]}]}],
    }]


@pytest.mark.parametrize("price", [-110.5, -110.0, True, "-110.9", 5, None, "-" + "9" * 5000])
def test_provider_cannot_silently_truncate_american_odds(price):
    with pytest.raises(TheOddsApiError, match="AMERICAN_ODDS_INVALID"):
        normalize_response(_provider_payload(price), sport_key="americanfootball_nfl", captured_at=NOW)


@pytest.mark.parametrize("point", [float("nan"), float("inf"), "not-a-line", True, False])
def test_provider_refuses_invalid_point_before_admission(point):
    with pytest.raises(TheOddsApiError, match="POINT_INVALID"):
        normalize_response(_provider_payload(-110, point), sport_key="americanfootball_nfl", captured_at=NOW)


def test_provider_valid_integer_string_is_exact_and_receipt_is_bound():
    quotes = normalize_response(_provider_payload("-110"), sport_key="americanfootball_nfl", captured_at=NOW)
    assert len(quotes) == 1
    assert quotes[0].american_odds == -110
    assert quotes[0].point == 42.5
    assert len(quotes[0].raw_payload_sha256) == 64


@pytest.mark.parametrize("bad_line", [float("inf"), -float("inf"), float("nan"), 1e308])
def test_complement_nonfinite_or_overflowed_line_blocks_instead_of_crashing(bad_line):
    assert complement_model_p({"model_p": 0.55, "line": bad_line}, market="TOTALS") is None


@pytest.mark.parametrize("odds", [float("inf"), float("nan"), -110.5, -90, True, "garbage", "--110", "+-110", "++110", "9" * 5000])
def test_sibling_quotes_never_copy_invalid_prices(odds):
    rows = [
        {"market": "TOTALS", "event_id": "e1", "side": "OVER", "line": 42.5, "american_odds": -110},
        {"market": "TOTALS", "event_id": "e1", "side": "UNDER", "line": 42.5, "american_odds": odds},
    ]
    paired = attach_sibling_quotes(rows, group_key=lambda r: r["market"], side_of=lambda r: r["side"])
    assert paired[0].get("opposite_odds") is None


def test_sibling_quotes_require_opposing_market_selections():
    rows = [
        {"market": "TOTALS", "event_id": "e1", "side": "OVER", "line": 42.5, "american_odds": -110},
        {"market": "TOTALS", "event_id": "e1", "side": "HOME", "line": 42.5, "american_odds": -115},
    ]
    paired = attach_sibling_quotes(rows, group_key=lambda r: r["market"], side_of=lambda r: r["side"])
    assert all(r.get("opposite_odds") is None for r in paired)


def test_sibling_quotes_copy_only_unique_valid_complement():
    rows = [
        {"market": "TOTALS", "event_id": "e1", "side": "OVER", "line": 42.5, "american_odds": -110, "model_p": 0.55},
        {"market": "TOTALS", "event_id": "e1", "side": "UNDER", "line": 42.5, "american_odds": -105, "model_p": 0.45},
    ]
    paired = attach_sibling_quotes(rows, group_key=lambda r: r["market"], side_of=lambda r: r["side"])
    assert paired[0]["opposite_odds"] == -105
    assert paired[1]["opposite_odds"] == -110
    assert complement_model_p(paired[0], market="TOTALS") == 0.45


@pytest.mark.parametrize("other_line", [43.5, None, float("inf"), True])
def test_sibling_quotes_refuse_different_or_missing_total_threshold(other_line):
    rows = [
        {"market": "TOTALS", "event_id": "e1", "side": "OVER", "line": 42.5, "american_odds": -110},
        {"market": "TOTALS", "event_id": "e1", "side": "UNDER", "line": other_line, "american_odds": -105},
    ]
    paired = attach_sibling_quotes(rows, group_key=lambda row: row["market"], side_of=lambda row: row["side"])
    assert all(row.get("opposite_odds") is None for row in paired)


@pytest.mark.parametrize("different_field", ["event_id", "entity_id", "provider"])
def test_sibling_quotes_refuse_different_identity_even_with_weak_group_key(different_field):
    rows = [
        {"market": "TOTALS", "side": "OVER", "line": 42.5, different_field: "a", "american_odds": -110},
        {"market": "TOTALS", "side": "UNDER", "line": 42.5, different_field: "b", "american_odds": -105},
    ]
    paired = attach_sibling_quotes(rows, group_key=lambda row: row["market"], side_of=lambda row: row["side"])
    assert all(row.get("opposite_odds") is None for row in paired)


def test_sibling_quotes_allow_opposite_spread_handicaps():
    rows = [
        {"market": "SPREAD", "event_id": "e1", "team_side": "HOME", "side": "HOME", "line": -3.5, "american_odds": -110},
        {"market": "SPREAD", "event_id": "e1", "team_side": "AWAY", "side": "AWAY", "line": 3.5, "american_odds": -105},
    ]
    paired = attach_sibling_quotes(rows, group_key=lambda row: row["market"], side_of=lambda row: row["side"])
    assert paired[0]["opposite_odds"] == -105
    assert paired[1]["opposite_odds"] == -110


@pytest.mark.parametrize("different_field", ["book", "captured_at", "price_captured_at"])
def test_siblings_refuse_different_books_or_capture_clocks(different_field):
    rows = [
        {"market": "TOTALS", "event_id": "e1", "side": "OVER", "line": 42.5,
         "american_odds": -110, different_field: "a"},
        {"market": "TOTALS", "event_id": "e1", "side": "UNDER", "line": 42.5,
         "american_odds": -105, different_field: "b"},
    ]
    paired = attach_sibling_quotes(rows, group_key=lambda row: row["market"], side_of=lambda row: row["side"])
    assert all(row.get("opposite_odds") is None for row in paired)


def test_siblings_refuse_missing_event_even_when_market_line_match():
    rows = [
        {"market": "TOTALS", "side": "OVER", "line": 42.5, "american_odds": -110},
        {"market": "TOTALS", "side": "UNDER", "line": 42.5, "american_odds": -105},
    ]
    paired = attach_sibling_quotes(rows, group_key=lambda row: row["market"], side_of=lambda row: row["side"])
    assert all(row.get("opposite_odds") is None for row in paired)


def test_siblings_refuse_invalid_candidate_own_price():
    rows = [
        {"market": "TOTALS", "event_id": "e1", "side": "OVER", "line": 42.5, "american_odds": float("nan")},
        {"market": "TOTALS", "event_id": "e1", "side": "UNDER", "line": 42.5, "american_odds": -105},
    ]
    paired = attach_sibling_quotes(rows, group_key=lambda row: row["market"], side_of=lambda row: row["side"])
    assert all(row.get("opposite_odds") is None for row in paired)


def test_public_context_receipt_must_be_sha256_hex():
    with pytest.raises(MarketDataContractError, match="RAW_PAYLOAD_SHA256_INVALID"):
        PublicBettingSplit(
            source="ACTION_NETWORK", sport_key="NFL", event_key="g", market="SPREAD",
            selection="HOME", ticket_percent=50., money_percent=50., captured_at=NOW,
            raw_payload_sha256="x" * 64,
        )
