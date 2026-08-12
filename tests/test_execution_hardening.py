import tempfile
from pathlib import Path

import pytest

from sportsedge.clv_capture import CLVCaptureError, capture_closing_line
from sportsedge.decision_ledger import build_decision_ledger
from sportsedge.execution_reservation import ExecutionReservationError, finalize_reservation, reserve_wager


def _payload(book="draftkings", odds=-110, line=8.5):
    return {
        "slate_date_ct": "2026-08-12",
        "generated_at_utc": "2026-08-12T15:00:00+00:00",
        "run_status": "PASS",
        "provider_status": [{"provider": "ESPN_WEB_HEADER_DRAFTKINGS", "status": "PASS"}],
        "results": [{
            "source_index": 0,
            "game_id": "123",
            "market": "TOTALS",
            "entity_id": "",
            "line": line,
            "side": "OVER",
            "book_key": book,
            "american_odds": odds,
            "model_p": 0.57,
            "bet_status": "OFFICIAL_BET",
            "reason": "TRUTH_GATE_PASS",
        }],
    }


def _decision(run_id="run-1", **kwargs):
    return build_decision_ledger(_payload(**kwargs), run_id=run_id)["decisions"][0]


def test_same_bet_across_runs_has_same_wager_key_despite_price_move():
    a = _decision(run_id="run-1", odds=-110)
    b = _decision(run_id="run-2", odds=-105)
    assert a["decision_id"] != b["decision_id"]
    assert a["wager_key"] == b["wager_key"]


def test_reservation_is_atomic_and_second_claim_fails():
    d = _decision()
    with tempfile.TemporaryDirectory() as td:
        first = reserve_wager(d, td)
        assert first["status"] == "RESERVED"
        with pytest.raises(ExecutionReservationError, match="WAGER_ALREADY_RESERVED"):
            reserve_wager(d, td)


def test_only_official_exact_book_decisions_can_reserve():
    d = _decision()
    d["bet_status"] = "PASS"
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(ExecutionReservationError, match="ONLY_OFFICIAL_BET_CAN_RESERVE"):
            reserve_wager(d, td)


def test_finalized_reservation_cannot_be_finalized_twice():
    d = _decision()
    with tempfile.TemporaryDirectory() as td:
        reserve_wager(d, td)
        out = finalize_reservation(td, d["wager_key"], status="PLACED", sportsbook_bet_id="abc")
        assert out["status"] == "PLACED"
        with pytest.raises(ExecutionReservationError, match="RESERVATION_ALREADY_FINALIZED"):
            finalize_reservation(td, d["wager_key"], status="PLACED")


def test_clv_matches_only_exact_book_line_market_side():
    d = _decision()
    close = [{"book_key": "draftkings", "game_id": "123", "market": "TOTALS", "entity_id": "", "line": 8.5, "side": "OVER", "american_odds": -120, "retrieved_at": "2026-08-12T18:59:00Z"}]
    out = capture_closing_line(d, close)
    assert out["status"] == "MATCHED"
    assert out["closing_odds"] == -120


def test_clv_never_substitutes_nearby_line_or_other_book():
    d = _decision()
    close = [
        {"book_key": "draftkings", "game_id": "123", "market": "TOTALS", "entity_id": "", "line": 9.0, "side": "OVER", "american_odds": -110},
        {"book_key": "fanduel", "game_id": "123", "market": "TOTALS", "entity_id": "", "line": 8.5, "side": "OVER", "american_odds": -110},
    ]
    out = capture_closing_line(d, close)
    assert out["status"] == "NO_CLOSING_LINE"


def test_duplicate_exact_closes_fail_closed():
    d = _decision()
    q = {"book_key": "draftkings", "game_id": "123", "market": "TOTALS", "entity_id": "", "line": 8.5, "side": "OVER", "american_odds": -120}
    with pytest.raises(CLVCaptureError, match="AMBIGUOUS_EXACT_CLOSING_LINE"):
        capture_closing_line(d, [q, dict(q)])
