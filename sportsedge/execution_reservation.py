"""Atomic, fail-closed reservation primitive for future wager execution.

This module does not place bets. It exists so any future placement adapter must
claim an exact wager identity before contacting a sportsbook.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Mapping


class ExecutionReservationError(RuntimeError):
    pass


def reserve_wager(decision: Mapping[str, Any], root: str | Path) -> dict[str, Any]:
    if decision.get("bet_status") != "OFFICIAL_BET":
        raise ExecutionReservationError("ONLY_OFFICIAL_BET_CAN_RESERVE")
    wager_key = str(decision.get("wager_key") or "").strip()
    if not wager_key:
        raise ExecutionReservationError("WAGER_KEY_MISSING")
    if not str(decision.get("book_key") or "").strip():
        raise ExecutionReservationError("BOOK_KEY_MISSING")

    p = Path(root) / f"{wager_key}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "sportsedge_execution_reservation_v1",
        "wager_key": wager_key,
        "decision_id": decision.get("decision_id"),
        "book_key": decision.get("book_key"),
        "game_id": decision.get("game_id"),
        "market": decision.get("market"),
        "entity_id": decision.get("entity_id"),
        "line": decision.get("line"),
        "side": decision.get("side"),
        "status": "RESERVED",
        "reserved_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(p, flags, 0o600)
    except FileExistsError as exc:
        raise ExecutionReservationError("WAGER_ALREADY_RESERVED") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(record, fh, sort_keys=True)
            fh.write("\n")
    except Exception:
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        raise
    return record


def finalize_reservation(root: str | Path, wager_key: str, *, status: str, sportsbook_bet_id: str | None = None) -> dict[str, Any]:
    if status not in {"PLACED", "RELEASED", "FAILED"}:
        raise ExecutionReservationError("INVALID_FINAL_STATUS")
    p = Path(root) / f"{wager_key}.json"
    if not p.exists():
        raise ExecutionReservationError("RESERVATION_NOT_FOUND")
    current = json.loads(p.read_text(encoding="utf-8"))
    if current.get("status") != "RESERVED":
        raise ExecutionReservationError("RESERVATION_ALREADY_FINALIZED")
    current["status"] = status
    current["finalized_at_utc"] = datetime.now(timezone.utc).isoformat()
    current["sportsbook_bet_id"] = sportsbook_bet_id
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return current
