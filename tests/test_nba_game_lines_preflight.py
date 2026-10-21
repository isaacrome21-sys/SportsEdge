"""NBA game-line dry-run source preflight adversarial tests.

These tests never start the unapproved 2026 NBA game-lines clock.
They do not imply a new candidate is historically accurate.
"""
from copy import deepcopy
import pytest

from sportsedge.forward_validation.nba_game_lines_preflight import (
    VERSION, GameLinePreflightError, audit_nba_game_line_capture_preflight,
)


def quote(side, at, odds=-110, digest="a"):
    return {"side": side, "american_odds": odds,
            "quote_at_utc": at, "receipt_sha256": digest * 64}


def capture(*, market="TOTAL", cap_id="entry1", at="2026-10-21T18:30:00Z",
            q_at="2026-10-21T18:29:00Z", line=222.5,
            sides=("OVER", "UNDER")):
    return {
        "event_id": "NBA-game-ABC",
        "market": market,
        "line": line,
        "capture_id": cap_id,
        "captured_at_utc": at,
        "bookmaker": "DraftKings",
        "quotes": [quote(s, q_at, digest=chr(ord("a")+i))
                   for i, s in enumerate(sides)],
    }


def fixture(*, market="TOTAL", close=True):
    sides = ("HOME", "AWAY") if market != "TOTAL" else ("OVER", "UNDER")
    line = None if market == "MONEYLINE" else (3.5 if market == "SPREAD" else 222.5)
    c = capture(market=market, line=line, sides=sides)
    closes = [capture(
        market=market, cap_id="close1",
        at="2026-10-21T19:45:00Z", q_at="2026-10-21T19:44:00Z",
        line=line, sides=sides)] if close else []
    return {
        "event_id": "NBA-game-ABC",
        "event_start_utc": "2026-10-21T20:00:00Z",
        "fixture_source_sha256": "f" * 64,
        "market": market,
        "entry": c,
        "closes": closes,
    }


def audit(x):
    return audit_nba_game_line_capture_preflight({
        "schema": VERSION, "fixtures": [x]})


@pytest.mark.parametrize("market", ["MONEYLINE", "SPREAD", "TOTAL"])
def test_real_two_side_capture_structure_is_still_dry_run(market):
    report = audit(fixture(market=market))
    assert report["status"] == "DRY_RUN_ONLY_PREREG_NOT_FROZEN"
    assert report["clock_started"] is False
    assert report["historical_accuracy_screen_passed"] is False
    assert report["countable_prospective_rows"] == 0
    assert report["verdict"] == "NO_VERDICT_DRAFT"
    assert not report["eligibility"] and not report["play_authority"]
    row = report["diagnostic_rows"][0]
    assert row["market"] == market
    assert row["classification"] == "CLOSE_PAIR_FOUND_NOT_CERTIFIED"
    assert row["missing_close_reason"] is None
    assert not row["source_fixture_independently_verified"]
    assert "NBA-game-ABC" not in str(report)


@pytest.mark.parametrize("market", ["MONEYLINE", "SPREAD", "TOTAL"])
def test_missing_close_never_filled_from_entry(market):
    x = audit(fixture(market=market, close=False))
    row = x["diagnostic_rows"][0]
    assert row["classification"] == "CLV_MISSING"
    assert row["missing_close_reason"] == "NO_CLOSE_ROW"
    assert x["countable_prospective_rows"] == 0


def test_moved_spread_line_not_synthetically_rebased():
    x = fixture(market="SPREAD")
    x["closes"][0]["line"] = 4.5
    row = audit(x)["diagnostic_rows"][0]
    assert row["missing_close_reason"] == "LINE_MOVED"


def test_moved_total_line_not_synthetically_rebased():
    x = fixture(market="TOTAL")
    x["closes"][0]["line"] = 223.5
    assert audit(x)["diagnostic_rows"][0]["missing_close_reason"] == "LINE_MOVED"


def test_incomplete_close_pair_no_unearned_no_vig():
    x = fixture(market="TOTAL")
    x["closes"][0]["quotes"] = x["closes"][0]["quotes"][:1]
    r = audit(x)
    assert r["diagnostic_rows"][0]["missing_close_reason"] == "CLOSE_SINGLE_SIDED"
    assert not hasattr(r, "fair_probabilities")


def test_moneyline_single_side_uses_draft_market_missing_rule():
    x = fixture(market="MONEYLINE")
    x["closes"][0]["quotes"] = x["closes"][0]["quotes"][:1]
    assert audit(x)["diagnostic_rows"][0]["missing_close_reason"] == "LINE_MOVED"


def test_close_at_tipoff_is_not_pre_tip():
    x = fixture()
    x["closes"][0]["captured_at_utc"] = "2026-10-21T20:00:00Z"
    x["closes"][0]["quotes"] = [
        quote("OVER", "2026-10-21T19:59:00Z"),
        quote("UNDER", "2026-10-21T19:59:00Z", digest="b"),
    ]
    assert audit(x)["diagnostic_rows"][0]["missing_close_reason"] == "CLOSE_NOT_PREKICKOFF"


def test_exact_60_minute_close_is_valid_but_60m1s_is_stale():
    x = fixture()
    x["closes"][0]["captured_at_utc"] = "2026-10-21T19:00:00Z"
    x["closes"][0]["quotes"] = [
        quote("OVER", "2026-10-21T18:59:00Z"),
        quote("UNDER", "2026-10-21T18:59:00Z", digest="b"),
    ]
    assert audit(x)["diagnostic_rows"][0]["missing_close_reason"] is None
    x["closes"][0]["captured_at_utc"] = "2026-10-21T18:59:59Z"
    x["closes"][0]["quotes"] = [
        quote("OVER", "2026-10-21T18:58:59Z"),
        quote("UNDER", "2026-10-21T18:58:59Z", digest="b"),
    ]
    assert audit(x)["diagnostic_rows"][0]["missing_close_reason"] == "CLOSE_STALE"


def test_latest_of_pretip_committed_captures_used_not_posttip():
    x = fixture()
    late = deepcopy(x["closes"][0])
    late["capture_id"] = "post_tip"
    late["captured_at_utc"] = "2026-10-21T20:05:00Z"
    late["quotes"] = [
        quote("OVER", "2026-10-21T20:04:00Z"),
        quote("UNDER", "2026-10-21T20:04:00Z", digest="b"),
    ]
    x["closes"].append(late)
    assert audit(x)["diagnostic_rows"][0]["missing_close_reason"] is None


def test_conflicting_last_pretip_capture_refused_not_best_shopped():
    x = fixture()
    late = deepcopy(x["closes"][0])
    late["capture_id"] = "close2"
    late["quotes"][0]["american_odds"] = -250
    x["closes"].append(late)
    with pytest.raises(GameLinePreflightError,
                       match="AMBIGUOUS_LAST_PRETIP_CAPTURE"):
        audit(x)


def test_post_start_entry_is_excluded_without_retro_clock():
    x = fixture()
    x["entry"]["captured_at_utc"] = "2026-10-21T20:01:00Z"
    x["entry"]["quotes"] = [
        quote("OVER", "2026-10-21T20:00:30Z"),
        quote("UNDER", "2026-10-21T20:00:30Z", digest="b"),
    ]
    row = audit(x)["diagnostic_rows"][0]
    assert row["classification"] == "ENTRY_NOT_PRE_EVENT"
    assert row["missing_close_reason"] == "ENTRY_NOT_PRE_EVENT"


@pytest.mark.parametrize("field,value,error", [
    ("bookmaker", "SomeOtherBook", "NOT_INDEPENDENT_DRAFTKINGS_CAPTURE"),
    ("line", float("nan"), "SPREAD_TOTAL_HALF_POINT_LINE_REQUIRED"),
    ("line", 223.25, "SPREAD_TOTAL_HALF_POINT_LINE_REQUIRED"),
])
def test_input_market_contract_and_nonfinite_prices_fail_closed(field,value,error):
    x = fixture()
    x["entry"][field] = value
    with pytest.raises(GameLinePreflightError,match=error):
        audit(x)


@pytest.mark.parametrize("bad", [-99, 0, 99, float("nan"), "110", True])
def test_invalid_quote_not_matched_as_real_bookmaker_price(bad):
    x = fixture()
    x["entry"]["quotes"][0]["american_odds"] = bad
    with pytest.raises(GameLinePreflightError,match="INVALID_AMERICAN_ODDS"):
        audit(x)


def test_too_old_or_noncontemporaneous_quote_receipts_refused():
    x = fixture()
    x["entry"]["quotes"][0]["quote_at_utc"] = "2026-10-21T18:24:00Z"
    with pytest.raises(GameLinePreflightError, match="QUOTE_AGE_OR_CHRONOLOGY_INVALID"):
        audit(x)
    x = fixture()
    x["entry"]["quotes"][0]["quote_at_utc"] = "2026-10-21T18:27:00Z"
    # 2 minutes from entry capture (<180 age), but 2 min from other
    # quote is <=150; move second quote to 18:29:59 for >150 gap.
    x["entry"]["quotes"][1]["quote_at_utc"] = "2026-10-21T18:29:59Z"
    with pytest.raises(GameLinePreflightError,
                       match="CAPTURE_PAIR_SPAN_EXCEEDS_150S"):
        audit(x)


def test_sender_cannot_assert_freeze_or_market_pass():
    x = {"schema": VERSION, "fixtures": [fixture()],
         "owner_approved": True, "historical_screen_passed": True}
    with pytest.raises(GameLinePreflightError, match="DRAFT_PREFLIGHT_SCHEMA_ONLY"):
        audit_nba_game_line_capture_preflight(x)


def test_out_of_scope_props_never_map_to_game_market():
    x = fixture()
    x["market"] = "player_points"
    with pytest.raises(GameLinePreflightError, match="MARKET_OUT_OF_SCOPE"):
        audit(x)


def test_duplicate_game_market_not_double_counted():
    x = fixture()
    with pytest.raises(GameLinePreflightError,match="DUPLICATE_EVENT_MARKET"):
        audit_nba_game_line_capture_preflight({
            "schema": VERSION, "fixtures": [x, deepcopy(x)]})


def test_determinism_without_modifying_input_or_producing_clv_verdict():
    x = fixture()
    old = deepcopy(x)
    a, b = audit(x), audit(x)
    assert a == b
    assert x == old
    assert all("CLV" not in k for k in a if k != "diagnostic_rows")
    assert a["countable_prospective_rows"] == 0


@pytest.mark.parametrize("field,bad", [
    ("market", []), ("market", {"selection": "TOTAL"}),
])
def test_hostile_unhashable_market_identity_refuses_safely(field, bad):
    x = fixture()
    x[field] = bad
    with pytest.raises(GameLinePreflightError, match="MARKET_OUT_OF_SCOPE"):
        audit(x)


def test_hostile_nonstring_quote_side_refuses_safely():
    x = fixture()
    x["entry"]["quotes"][0]["side"] = ["OVER"]
    with pytest.raises(GameLinePreflightError,
                       match="DUPLICATE_OR_UNKNOWN_QUOTE_SIDE"):
        audit(x)
