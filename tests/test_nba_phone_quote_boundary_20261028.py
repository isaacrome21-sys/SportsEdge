"""Adversarial intake tests: NBA phone quotes are syntax-only, never authenticated DK evidence.

The legacy research pricing path must not turn missing timestamps, NaN/Inf,
boolean lines, or non-American odds into a candidate/EV row. These tests
do not validate fixture membership, provider provenance, CLV, or a model.
"""
from datetime import datetime, timezone
import math

import pytest

from sportsedge.nba_phone_prop_pricing import (
    QUOTE_PRICE_INVALID, QUOTE_PRICE_MISSING,
    QUOTE_TIMESTAMP_INVALID, QUOTE_TIMESTAMP_MISSING,
    LINE_MISSING, BOOK_UNVERIFIED, QUOTE_NOT_PRE_EVENT,
    TARGET_START_INVALID, _american_to_decimal, phone_nba_prop_rows,
)

NOW = datetime(2026, 10, 28, 6, 0, tzinfo=timezone.utc)


class _Store:
    counters = {"records_kept": 48}

    def __init__(self):
        self.price_calls = 0

    def player_ids(self):
        return ["p1"]

    def player_name(self, player_id):
        assert player_id == "p1"
        return "Test Guard"

    def price(self, player_id, stat, line, target):
        self.price_calls += 1
        assert player_id == "p1" and stat == "points"
        assert line == 19.5
        return {
            "status": "PRICED", "player_name": "Test Guard",
            "p_over": 0.8, "p_under": 0.2, "p_push": 0.0,
            "n_prior": 12, "pool_n": 36, "pool_source": "TEST",
            "b1_fallback_to_b2": False, "weight_player": 0.5,
            "weight_pool": 0.5, "k_smooth": 5, "model_mean": 20.0,
            "position_group": "G", "history_basis": "TEST",
            "participation_feed": "NOT_WIRED", "limitation": "TEST",
            "construction": "TEST",
        }


def _row(**updates):
    row = {
        "sport": "NBA", "market": "PLAYER_POINTS",
        "player_name": "Test Guard", "side": "OVER",
        "line": 19.5, "odds": -110, "book": "draftkings",
        "tipoff": "2026-11-01T20:00:00-05:00",
        "quote_captured_at": "2026-10-28T05:59:00+00:00",
    }
    row.update(updates)
    return row


@pytest.mark.parametrize("odds", [
    "nan", "+inf", "-inf", "1e999", "+50", "-50",
    0, True, False, 50, -50, "+110.5", "100.0",
    float("nan"), float("inf"), float("-inf"),
    [], {}, "1e2", "−110", "１２５",
])
def test_malformed_odds_fail_before_model_price(odds):
    store = _Store()
    (out,), _ = phone_nba_prop_rows([_row(odds=odds)], now=NOW, store=store)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["blocker"] == QUOTE_PRICE_INVALID
    assert "model_p" not in out and "ev_per_dollar" not in out
    assert store.price_calls == 0


@pytest.mark.parametrize("odds", [None, ""])
def test_missing_odds_refused_separately(odds):
    store = _Store()
    (out,), _ = phone_nba_prop_rows([_row(odds=odds)], now=NOW, store=store)
    assert out["blocker"] == QUOTE_PRICE_MISSING
    assert store.price_calls == 0


@pytest.mark.parametrize("raw_ts, reason", [
    (None, QUOTE_TIMESTAMP_MISSING),
    ("", QUOTE_TIMESTAMP_MISSING),
    ("not-a-timestamp", QUOTE_TIMESTAMP_INVALID),
    ("2026-10-28T05:59:00", QUOTE_TIMESTAMP_INVALID),
    ("2026-10-28", QUOTE_TIMESTAMP_INVALID),
])
def test_missing_or_unaware_timestamp_refused_before_pricing(raw_ts, reason):
    store = _Store()
    (out,), _ = phone_nba_prop_rows(
        [_row(quote_captured_at=raw_ts)], now=NOW, store=store)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["blocker"] == reason
    assert "model_p" not in out and "ev_per_dollar" not in out
    assert store.price_calls == 0


def test_timestamp_key_absent_is_not_current_by_default():
    store = _Store()
    row = _row()
    del row["quote_captured_at"]
    (out,), _ = phone_nba_prop_rows([row], now=NOW, store=store)
    assert out["blocker"] == QUOTE_TIMESTAMP_MISSING
    assert store.price_calls == 0


@pytest.mark.parametrize("line", [True, False, "nan", "inf", "-inf", float("nan")])
def test_nonfinite_or_boolean_line_refused_before_pricing(line):
    store = _Store()
    (out,), _ = phone_nba_prop_rows([_row(line=line)], now=NOW, store=store)
    assert out["blocker"] == LINE_MISSING
    assert store.price_calls == 0


@pytest.mark.parametrize("line", [-1.5, -0.5, -1, "-100", float("-inf")])
def test_negative_stat_lines_refused_before_model_price(line):
    store = _Store()
    (out,), _ = phone_nba_prop_rows([_row(line=line)], now=NOW, store=store)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["blocker"] == LINE_MISSING
    assert "model_p" not in out and "ev_per_dollar" not in out
    assert store.price_calls == 0


@pytest.mark.parametrize("book", [None, "", "   ", 0, False, [], {}])
def test_missing_or_invalid_book_cannot_be_labeled_draftkings(book):
    store = _Store()
    (out,), _ = phone_nba_prop_rows([_row(book=book)], now=NOW, store=store)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["blocker"] == BOOK_UNVERIFIED
    assert "model_p" not in out and "ev_per_dollar" not in out
    assert store.price_calls == 0


def test_explicit_book_is_caller_assertion_not_provider_authentication():
    store = _Store()
    (out,), _ = phone_nba_prop_rows([_row(book=" FanDuel ")], now=NOW, store=store)
    assert store.price_calls == 1
    assert out["book"] == "FanDuel"
    assert out["book_provenance"] == "CALLER_ASSERTED_NOT_AUTHENTICATED"
    assert out["eligible"] is False and out["official_authority"] is False


@pytest.mark.parametrize("odds", ["+110", -110, 100, "-100", " +105 "])
def test_valid_integer_american_odds_keep_research_only_status(odds):
    store = _Store()
    (out,), _ = phone_nba_prop_rows([_row(odds=odds)], now=NOW, store=store)
    assert store.price_calls == 1
    assert out["status"] in {"PRICED_RESEARCH", "RESEARCH_CANDIDATE_NOT_VALIDATED"}
    assert math.isfinite(out["ev_per_dollar"])
    assert out["eligible"] is False and out["promotable"] is False
    assert out["research_only"] is True
    assert out["quote_freshness"] == "CURRENT"
    assert _american_to_decimal(odds) > 1.0


def test_legacy_captured_at_fallback_is_syntactic_not_provider_authentication():
    store = _Store()
    row = _row()
    row["captured_at"] = row.pop("quote_captured_at")
    (out,), _ = phone_nba_prop_rows([row], now=NOW, store=store)
    assert out["status"] in {"PRICED_RESEARCH", "RESEARCH_CANDIDATE_NOT_VALIDATED"}
    assert out["official_authority"] is False
    assert out["model_p_authority"] is False
    assert out["staking_authority"] is False

@pytest.mark.parametrize("start", [
    "2026-10-28T05:59:00+00:00",  # quote exactly at tip
    "2026-10-28T05:58:00+00:00",  # quote one minute after tip
    "2026-10-27T23:58:00-06:00",  # same instant, different offset
])
def test_post_tip_quote_refused_before_model_price(start):
    store = _Store()
    (out,), _ = phone_nba_prop_rows([_row(tipoff=start)], now=NOW, store=store)
    assert out["status"] == "NO_MODEL_OR_MARKET"
    assert out["blocker"] == QUOTE_NOT_PRE_EVENT
    assert "model_p" not in out and "ev_per_dollar" not in out
    assert store.price_calls == 0


def test_malformed_asserted_start_refused_before_model_price():
    store = _Store()
    (out,), _ = phone_nba_prop_rows(
        [_row(tipoff="2026-10-28", date="2026-10-28")],
        now=NOW, store=store)
    assert out["blocker"] == TARGET_START_INVALID
    assert store.price_calls == 0


def test_conflicting_asserted_start_fields_fail_closed():
    store = _Store()
    (out,), _ = phone_nba_prop_rows(
        [_row(tipoff="2026-11-01T20:00:00-05:00",
              commence_time="2026-10-28T05:58:00+00:00")],
        now=NOW, store=store)
    assert out["blocker"] == QUOTE_NOT_PRE_EVENT
    assert store.price_calls == 0


def test_pre_tip_aware_start_stays_research_only():
    store = _Store()
    (out,), _ = phone_nba_prop_rows(
        [_row(tipoff="2026-10-28T06:01:00+00:00")],
        now=NOW, store=store)
    assert store.price_calls == 1
    assert out["status"] in {"PRICED_RESEARCH", "RESEARCH_CANDIDATE_NOT_VALIDATED"}
    assert out["eligible"] is False and out["official_authority"] is False
