"""Synthetic contract tests only: no provider admission or historical closes."""
from copy import deepcopy

import pytest

from sportsedge.mlb_game_line_receipt_audit import (
    MLBGameLineReceiptError,
    audit_game_line_receipt_manifest,
)


def fixture():
    return {
        "game_pk": 123,
        "official_date": "2027-04-01",
        "season_type": "R",
        "start_at_utc": "2027-04-01T20:00:00Z",
        "market": "TOTALS",
        "line": 8.5,
        "entry_capture_id": "entry",
        "close_capture_id": "close",
        "observations": [
            {"capture_id": "entry", "game_pk": 123, "market": "TOTALS",
             "line": 8.5, "book": "DraftKings",
             "captured_at_utc": "2027-04-01T18:40:00Z",
             "raw_sha256": "a" * 64, "prices": {"OVER": -110, "UNDER": -110}},
            {"capture_id": "close", "game_pk": 123, "market": "TOTALS",
             "line": 8.5, "book": "DraftKings",
             "captured_at_utc": "2027-04-01T19:50:00Z",
             "raw_sha256": "b" * 64, "prices": {"OVER": -115, "UNDER": -105}},
        ],
        "archive_sealed_at_utc": "2027-04-01T20:01:00Z",
        "final": {"game_pk": 123, "source": "MLB_STATSAPI_FINAL",
                  "status": "FINAL", "captured_at_utc": "2027-04-01T23:05:00Z",
                  "away_score": 4, "home_score": 6, "raw_sha256": "c" * 64},
    }


def test_complete_shaped_manifest_does_not_grant_verification_or_count():
    row = audit_game_line_receipt_manifest(**fixture())
    assert row["status"] == "MANIFEST_SHAPED_RESEARCH_ONLY"
    assert row["last_archived_pregame_quote"] is True
    assert row["final_receipt_present"] is True
    assert row["actual_last_book_quote_proven"] is False
    assert row["archive_completeness_independently_verified"] is False
    assert row["counted"] is False
    assert row["verified_clv"] is False
    assert row["promotion_authority"] is False


@pytest.mark.parametrize("field,value,reason", [
    ("entry_capture_id", "close", "ENTRY_AND_CLOSE_NOT_DISTINCT"),
    ("close_capture_id", "missing", "ENTRY_OR_CLOSE_NOT_ARCHIVED"),
    ("archive_sealed_at_utc", "2027-04-01T19:59:00Z", "ARCHIVE_NOT_SEALED_AFTER_START"),
    ("market", "TEAM_TOTALS", "GAME_LINE_MARKET_NOT_FROZEN"),
])
def test_structural_refusals(field, value, reason):
    data = fixture()
    data[field] = value
    with pytest.raises(MLBGameLineReceiptError, match=reason):
        audit_game_line_receipt_manifest(**data)


@pytest.mark.parametrize("key,value,reason", [
    ("captured_at_utc", "2027-04-01T18:40:00Z", "ENTRY_CLOSE_ORDER_INVALID"),
    ("captured_at_utc", "2027-04-01T20:00:00Z", "ENTRY_CLOSE_ORDER_INVALID"),
    ("captured_at_utc", "2027-04-01T18:59:00Z", "CLOSE_OUTSIDE_PRESTART_WINDOW"),
    ("game_pk", 124, "CAPTURE_CONTRACT_MISMATCH"),
    ("book", "Pinnacle", "CAPTURE_BOOK_MISMATCH"),
    ("line", 7.5, "CAPTURE_CONTRACT_MISMATCH"),
    ("raw_sha256", "claimed", "CAPTURE_RAW_SHA_MISSING"),
    ("prices", {"OVER": -110}, "TWO_SIDED_QUOTE_MISSING"),
    ("prices", {"OVER": -110, "UNDER": float("nan")}, "TWO_SIDED_PRICE_INVALID"),
])
def test_close_quote_must_be_same_contract_and_valid(key, value, reason):
    data = fixture()
    data["observations"][1][key] = value
    with pytest.raises(MLBGameLineReceiptError, match=reason):
        audit_game_line_receipt_manifest(**data)


def test_close_refused_when_later_pregame_quote_is_archived():
    data = fixture()
    later = deepcopy(data["observations"][1])
    later["capture_id"] = "later"
    later["captured_at_utc"] = "2027-04-01T19:55:00Z"
    data["observations"].append(later)
    with pytest.raises(MLBGameLineReceiptError, match="CLOSE_NOT_UNIQUELY_LAST_ARCHIVED_QUOTE"):
        audit_game_line_receipt_manifest(**data)


def test_equal_time_last_quote_is_ambiguous_not_a_lexical_tiebreak():
    data = fixture()
    equal = deepcopy(data["observations"][1])
    equal["capture_id"] = "another"
    data["observations"].append(equal)
    with pytest.raises(MLBGameLineReceiptError, match="CLOSE_NOT_UNIQUELY_LAST_ARCHIVED_QUOTE"):
        audit_game_line_receipt_manifest(**data)


@pytest.mark.parametrize("key,value,reason", [
    ("game_pk", 124, "FINAL_GAME_ID_MISMATCH"),
    ("status", "LIVE", "OFFICIAL_FINAL_NOT_CAPTURED"),
    ("source", "UNVERIFIED_SNAPSHOT", "OFFICIAL_FINAL_NOT_CAPTURED"),
    ("raw_sha256", None, "FINAL_RAW_SHA_MISSING"),
    ("captured_at_utc", "2027-04-01T19:00:00Z", "FINAL_NOT_POSTSTART"),
    ("away_score", True, "FINAL_SCORE_INVALID"),
    ("away_score", 6, "FINAL_TIE_UNRESOLVED"),
])
def test_final_must_be_independent_game_matched_source_receipt(key, value, reason):
    data = fixture()
    data["final"][key] = value
    with pytest.raises(MLBGameLineReceiptError, match=reason):
        audit_game_line_receipt_manifest(**data)


def test_postseason_not_mixed_into_2027_regular_capture():
    data = fixture()
    data["season_type"] = "P"
    with pytest.raises(MLBGameLineReceiptError, match="POSTSEASON_SHAPED_SEPARATELY"):
        audit_game_line_receipt_manifest(**data)


@pytest.mark.parametrize("market,line,prices", [
    ("MONEYLINE", None, {"HOME": -120, "AWAY": +105}),
    ("RUN_LINE", -1.5, {"HOME": +140, "AWAY": -160}),
])
def test_other_two_frozen_game_markets_share_same_receipt_rules(market, line, prices):
    data = fixture()
    data["market"] = market
    data["line"] = line
    for observation in data["observations"]:
        observation["market"] = market
        observation["line"] = line
        observation["prices"] = dict(prices)
    assert audit_game_line_receipt_manifest(**data)["counted"] is False
