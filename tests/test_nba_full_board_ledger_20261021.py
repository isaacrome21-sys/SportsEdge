from __future__ import annotations

import copy

import pytest

from sportsedge.forward_validation.nba_full_board_ledger import (
    NbaFullBoardLedgerError,
    build_nba_props_entry_ledger,
)

CAPTURED = "2026-10-21T16:00:00-05:00"
RECORDED = "2026-10-21T16:00:20-05:00"
START = "2026-10-21T19:30:00-05:00"


def stamp():
    return {
        "engine_id": "NBA_PROP_EMPIRICAL_V1",
        "sufficiency_met": True,
        "n_prior": 12,
        "pool_n": 100,
        "pool_source": "POSITION_GROUP_EXPANDING_PIT",
        "history_basis": "STRICTLY_PRIOR_SAME_SEASON_GAMES",
        "participation_feed": "NOT_WIRED",
        "limitation": "No participation/minutes/availability feed is wired.",
    }


def raw(side="OVER", odds=-110, **over):
    row = {
        "sport": "NBA", "market": "PLAYER_POINTS", "side": side,
        "line": 24.5, "odds": odds, "book": "draftkings",
        "player_name": "Player One", "event_id": "evt-1",
        "capture_id": "cap-1", "commence_time": START,
        "quote_captured_at": CAPTURED, "away": "Away", "home": "Home",
    }
    row.update(over)
    return row


def priced(side="OVER", status="RESEARCH_CANDIDATE_NOT_VALIDATED", **over):
    row = {
        "status": status, "sport": "NBA", "market": "PLAYER_POINTS",
        "coverage_market": "player_points", "side": side,
        "selection": side, "player_name": "Player One", "player_id": "p1",
        "line": 24.5, "odds": -110, "p_over": .60,
        "p_under": .35, "p_push": .05, "nba_prop_engine": stamp(),
    }
    row.update(over)
    return row


def build(raws=None, priceds=None, **over):
    kwargs = dict(run_id="run-1", source_ref="records/oct21.json",
                  recorded_at=RECORDED, slate_date="2026-10-21")
    kwargs.update(over)
    return build_nba_props_entry_ledger(
        raws or [raw(), raw("UNDER")],
        priceds or [priced(), priced("UNDER", "PRICED_RESEARCH")],
        **kwargs,
    )


def test_builds_one_stable_picked_pair_and_normalizes_nonpush_mass():
    out = build()
    assert out["accounting"]["raw_rows"] == 2
    assert out["accounting"]["priced_side_rows"] == 2
    assert out["accounting"]["ledger_rows"] == 1
    assert out["accounting"]["picked_rows"] == 1
    assert out["accounting"]["conservation_ok"] is True
    row = out["ledger"][0]
    assert row["disposition"] == "PICKED"
    assert row["entry_prices"] == {"OVER": -110, "UNDER": -110}
    assert row["model_p"]["OVER"] == pytest.approx(.60 / .95)
    assert row["model_p"]["UNDER"] == pytest.approx(.35 / .95)
    assert sum(row["model_p"].values()) == pytest.approx(1.0)
    assert row["model_push_probability"] == .05
    assert row["label"] == "PROSPECTIVE"
    assert row["eligible"] is False and row["play_authority"] is False
    assert len(out["ledger_sha256"]) == 64
    assert build()["ledger"][0]["row_id"] == row["row_id"]


def test_records_passed_rows_not_only_candidates():
    out = build(priceds=[priced(status="PRICED_RESEARCH"),
                         priced("UNDER", "PRICED_RESEARCH")])
    assert out["ledger"][0]["disposition"] == "PASSED"
    assert out["accounting"]["passed_rows"] == 1


def test_single_sided_pair_is_rejected_and_accounted():
    out = build(raws=[raw()], priceds=[priced()])
    assert out["ledger"] == []
    assert out["accounting"]["unpaired_priced_rows"] == 1
    assert out["rejected"][0]["reason"] == "ENTRY_PAIR_INCOMPLETE"


def test_blocked_and_watch_rows_stay_visible_but_do_not_count():
    raws = [raw(), raw("UNDER"), raw(player_name="Blocked", capture_id="c2"),
            raw("UNDER", player_name="Blocked", capture_id="c2")]
    priceds = [priced(status="WATCH_QUOTE_NOT_CURRENT"),
               priced("UNDER", "WATCH_QUOTE_NOT_CURRENT"),
               priced(status="NO_MODEL_OR_MARKET", player_id=None,
                      coverage_market="player_points"),
               priced("UNDER", "NO_MODEL_OR_MARKET", player_id=None,
                      coverage_market="player_points")]
    out = build(raws, priceds)
    assert out["ledger"] == []
    assert out["accounting"]["watch_rows"] == 2
    assert out["accounting"]["blocked_rows"] == 2
    assert {r["reason"] for r in out["rejected"]} == {
        "WATCH_NOT_COUNTABLE", "UNPRICED_NOT_COUNTABLE"}


@pytest.mark.parametrize("field,value,reason", [
    ("capture_id", None, "CAPTURE_OR_EVENT_ID_MISSING"),
    ("event_id", None, "CAPTURE_OR_EVENT_ID_MISSING"),
    ("book", "otherbook", "BOOK_NOT_DRAFTKINGS"),
    ("commence_time", "2026-10-22T19:30:00-05:00", "EVENT_OUTSIDE_SLATE"),
    ("quote_captured_at", START, "ENTRY_NOT_PRE_EVENT"),
])
def test_identity_book_slate_and_pre_event_fail_closed(field, value, reason):
    raws = [raw(**{field: value}), raw("UNDER", **{field: value})]
    out = build(raws=raws)
    assert out["ledger"] == []
    assert {r["reason"] for r in out["rejected"]} == {reason}


def test_out_of_scope_rows_are_accounted_not_priced_into_ledger():
    raws = [raw(market="PLAYER_THREES"), raw("UNDER", market="PLAYER_THREES")]
    priceds = [priced(coverage_market=None), priced("UNDER", coverage_market=None)]
    out = build(raws, priceds)
    assert out["accounting"]["out_of_scope_rows"] == 2
    assert out["ledger"] == []


def test_duplicate_side_refuses_board():
    with pytest.raises(NbaFullBoardLedgerError) as exc:
        build(raws=[raw(), raw()], priceds=[priced(), priced()])
    assert exc.value.reason == "DUPLICATE_RAW_SIDE"


def test_pair_timestamp_and_distribution_mismatch_refuse_board():
    second = raw("UNDER", quote_captured_at="2026-10-21T16:00:01-05:00")
    with pytest.raises(NbaFullBoardLedgerError) as exc:
        build(raws=[raw(), second])
    assert exc.value.reason == "PAIR_CAPTURE_TIMESTAMP_MISMATCH"
    under = priced("UNDER", p_over=.59)
    with pytest.raises(NbaFullBoardLedgerError) as exc:
        build(priceds=[priced(), under])
    assert exc.value.reason == "PAIR_MODEL_DISTRIBUTION_MISMATCH"


def test_raw_priced_alignment_and_length_refuse():
    with pytest.raises(NbaFullBoardLedgerError) as exc:
        build_nba_props_entry_ledger([], [priced()], run_id="r", source_ref="s",
                                     recorded_at=RECORDED, slate_date="2026-10-21")
    assert exc.value.reason == "RAW_PRICED_LENGTH_MISMATCH"
    bad = priced(side="UNDER")
    with pytest.raises(NbaFullBoardLedgerError) as exc:
        build(priceds=[bad, priced("UNDER")])
    assert exc.value.reason == "RAW_PRICED_SIDE_MISMATCH"


def test_preboundary_and_poststart_recording_refuse_or_exclude():
    with pytest.raises(NbaFullBoardLedgerError) as exc:
        build(slate_date="2026-10-20")
    assert exc.value.reason == "SLATE_BEFORE_PROSPECTIVE_BOUNDARY"
    out = build(recorded_at="2026-10-21T19:31:00-05:00")
    assert out["ledger"] == [] and out["accounting"]["late_rows"] == 2


def test_mutating_return_does_not_change_stable_rebuild():
    first = build()
    mutated = copy.deepcopy(first)
    mutated["ledger"][0]["entry_prices"]["OVER"] = 999
    second = build()
    assert second["ledger"][0]["entry_prices"]["OVER"] == -110
    assert second["ledger_sha256"] == first["ledger_sha256"]
