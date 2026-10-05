from datetime import datetime, timezone

import pytest

from sportsedge.research.nfl_prop_usage_v1_2026_forward import (
    NflPropForwardError,
    classify_snapshot,
    select_forward_pairs,
)


LOCKED = "2026-10-05T12:20:00Z"


def row(observed, *, week=5, market="player_pass_yds", captured=None):
    return {
        "season": 2026,
        "week": week,
        "game_id": "2026_05_TB_DAL",
        "player_id": "00-0031234",
        "market": market,
        "book": "draftkings",
        "line": 249.5,
        "over_odds": -110,
        "under_odds": -110,
        "kickoff_at": "2026-10-09T00:15:00Z",
        "observed_at": observed,
        "captured_at": captured or observed,
    }


def test_decision_and_close_windows_are_disjoint_and_forward_only():
    decision = classify_snapshot(
        row("2026-10-08T23:30:00Z"), lock_merged_at=LOCKED
    )
    close = classify_snapshot(
        row("2026-10-09T00:05:00Z"), lock_merged_at=LOCKED
    )
    assert decision["forward_lane"] == "DECISION"
    assert close["forward_lane"] == "CLOSE"


def test_weeks_one_through_four_and_prelock_rows_are_rejected():
    with pytest.raises(NflPropForwardError, match="WEEK_NOT_FORWARD_WINDOW"):
        classify_snapshot(
            row("2026-10-08T23:30:00Z", week=4), lock_merged_at=LOCKED
        )
    with pytest.raises(NflPropForwardError, match="PRELOCK_EVIDENCE_FORBIDDEN"):
        classify_snapshot(
            row("2026-10-08T23:30:00Z", captured="2026-10-05T12:19:59Z"),
            lock_merged_at=LOCKED,
        )


def test_postkick_and_wrong_book_or_market_fail_closed():
    with pytest.raises(NflPropForwardError, match="POSTKICK_EVIDENCE_FORBIDDEN"):
        classify_snapshot(
            row("2026-10-09T00:15:01Z"), lock_merged_at=LOCKED
        )
    bad = row("2026-10-08T23:30:00Z")
    bad["book"] = "fanduel"
    with pytest.raises(NflPropForwardError, match="BOOK_NOT_FROZEN_DRAFTKINGS"):
        classify_snapshot(bad, lock_merged_at=LOCKED)
    with pytest.raises(NflPropForwardError, match="MARKET_NOT_FROZEN_V1"):
        classify_snapshot(
            row("2026-10-08T23:30:00Z", market="player_receptions"),
            lock_merged_at=LOCKED,
        )


def test_selector_keeps_latest_decision_and_optional_close():
    rows = [
        row("2026-10-08T23:10:00Z"),
        row("2026-10-08T23:30:00Z"),
        row("2026-10-09T00:01:00Z"),
        row("2026-10-09T00:10:00Z"),
    ]
    out = select_forward_pairs(rows, lock_merged_at=LOCKED)
    assert len(out["selected"]) == 1
    selected = out["selected"][0]
    assert selected["decision"]["observed_at"] == "2026-10-08T23:30:00+00:00"
    assert selected["close"]["observed_at"] == "2026-10-09T00:10:00+00:00"
    assert selected["validation_row_eligible"] is True
    assert selected["clv_row_eligible"] is True
    assert out["authority"]["research_only"] is True
    assert not any(v for k, v in out["authority"].items() if k != "research_only")
