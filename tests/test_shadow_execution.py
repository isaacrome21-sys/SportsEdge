import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sportsedge.execution_reservation import (
    ExecutionReservationError,
    finalize_reservation,
    recover_stale_reservation,
    reserve_wager,
)
from sportsedge.shadow_execution import ShadowExecutionError, execute_shadow

UTC = timezone.utc
NOW = datetime(2026, 8, 12, 15, 0, tzinfo=UTC)


def decision():
    return {
        "decision_id": "decision-1",
        "wager_key": "abc123",
        "execution_ready": True,
        "bet_status": "OFFICIAL_BET",
        "book_key": "draftkings",
        "game_id": "777",
        "market": "MONEYLINE",
        "entity_id": "",
        "line": None,
        "side": "HOME",
    }


def test_shadow_uses_real_reservation_during_stub_then_releases(tmp_path):
    seen = {}

    def stub(row):
        active = tmp_path / "abc123.json"
        assert active.exists()
        record = json.loads(active.read_text())
        assert record["status"] == "RESERVED"
        with pytest.raises(ExecutionReservationError, match="WAGER_ALREADY_RESERVED"):
            reserve_wager(row, tmp_path, now=NOW)
        seen["called"] = True
        return {"accepted": True, "reason": "SIMULATED_BOOK_ACCEPT"}

    result = execute_shadow(decision(), tmp_path, placement_stub=stub, now=NOW)
    assert seen["called"] is True
    assert result["execution_mode"] == "SHADOW"
    assert result["status"] == "RELEASED"
    assert not (tmp_path / "abc123.json").exists()
    archived = Path(result["reservation_archive"])
    assert archived.exists()
    record = json.loads(archived.read_text())
    assert record["status"] == "RELEASED"
    assert record["detail"] == "SIMULATED_BOOK_ACCEPT"
    assert record["sportsbook_bet_id"] is None


def test_shadow_rejection_archives_failed_and_frees_active_lock(tmp_path):
    result = execute_shadow(
        decision(),
        tmp_path,
        placement_stub=lambda row: {"accepted": False, "reason": "SIMULATED_PRICE_MOVED"},
        now=NOW,
    )
    assert result["status"] == "FAILED"
    assert result["detail"] == "SIMULATED_PRICE_MOVED"
    assert not (tmp_path / "abc123.json").exists()
    archived = json.loads(Path(result["reservation_archive"]).read_text())
    assert archived["status"] == "FAILED"


def test_shadow_exception_fails_closed_and_archives(tmp_path):
    def boom(row):
        raise RuntimeError("boom")

    with pytest.raises(ShadowExecutionError, match="SHADOW_PLACEMENT_EXCEPTION:RuntimeError"):
        execute_shadow(decision(), tmp_path, placement_stub=boom, now=NOW)
    assert not (tmp_path / "abc123.json").exists()
    history = list((tmp_path / "history").glob("abc123.failed.*.json"))
    assert len(history) == 1
    record = json.loads(history[0].read_text())
    assert record["status"] == "FAILED"
    assert record["detail"] == "SHADOW_EXCEPTION:RuntimeError"


def test_shadow_refuses_non_execution_ready_decision(tmp_path):
    row = decision()
    row["execution_ready"] = False
    with pytest.raises(ShadowExecutionError, match="DECISION_NOT_EXECUTION_READY"):
        execute_shadow(row, tmp_path, placement_stub=lambda x: {"accepted": True}, now=NOW)
    assert not list(tmp_path.glob("*.json"))


def test_fresh_reservation_is_not_recovered(tmp_path):
    reserve_wager(decision(), tmp_path, now=NOW)
    with pytest.raises(ExecutionReservationError, match="RESERVATION_NOT_STALE"):
        recover_stale_reservation(tmp_path, "abc123", max_age_seconds=900, now=NOW + timedelta(seconds=899))
    assert (tmp_path / "abc123.json").exists()


def test_stale_reservation_moves_to_failed_history_then_can_reacquire(tmp_path):
    reserve_wager(decision(), tmp_path, now=NOW)
    recovered = recover_stale_reservation(
        tmp_path,
        "abc123",
        max_age_seconds=900,
        now=NOW + timedelta(seconds=901),
    )
    assert recovered["status"] == "FAILED"
    assert recovered["detail"] == "STALE_RESERVATION_RECOVERED"
    assert not (tmp_path / "abc123.json").exists()
    reacquired = reserve_wager(decision(), tmp_path, now=NOW + timedelta(seconds=902))
    assert reacquired["status"] == "RESERVED"


def test_placed_reservation_is_never_auto_recoverable(tmp_path):
    reserve_wager(decision(), tmp_path, now=NOW)
    finalize_reservation(tmp_path, "abc123", status="PLACED", sportsbook_bet_id="bet-1", now=NOW + timedelta(seconds=1))
    with pytest.raises(ExecutionReservationError, match="PLACED_RESERVATION_NOT_RECOVERABLE"):
        recover_stale_reservation(tmp_path, "abc123", max_age_seconds=1, now=NOW + timedelta(hours=1))
    assert (tmp_path / "abc123.json").exists()
