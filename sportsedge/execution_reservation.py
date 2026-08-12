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


_INVALID_BOOK_KEYS = {"MISSING", "UNKNOWN", "LEGACY_BOOK_UNKNOWN"}


def _utc_now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ExecutionReservationError("NOW_TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc)


def _parse_utc(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception as exc:
        raise ExecutionReservationError("RESERVATION_TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExecutionReservationError("RESERVATION_TIMESTAMP_INVALID")
    return parsed.astimezone(timezone.utc)


def _active_path(root: str | Path, wager_key: str) -> Path:
    return Path(root) / f"{wager_key}.json"


def _history_path(root: str | Path, wager_key: str, *, suffix: str, now: datetime) -> Path:
    history = Path(root) / "history"
    history.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    return history / f"{wager_key}.{suffix}.{stamp}.{os.getpid()}.json"


def reserve_wager(decision: Mapping[str, Any], root: str | Path, *, now: datetime | None = None) -> dict[str, Any]:
    if decision.get("bet_status") != "OFFICIAL_BET":
        raise ExecutionReservationError("ONLY_OFFICIAL_BET_CAN_RESERVE")
    wager_key = str(decision.get("wager_key") or "").strip()
    if not wager_key:
        raise ExecutionReservationError("WAGER_KEY_MISSING")
    book_key = str(decision.get("book_key") or "").strip()
    if not book_key or book_key in _INVALID_BOOK_KEYS:
        raise ExecutionReservationError("BOOK_KEY_MISSING")

    current = _utc_now(now)
    p = _active_path(root, wager_key)
    p.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "sportsedge_execution_reservation_v2",
        "wager_key": wager_key,
        "decision_id": decision.get("decision_id"),
        "book_key": book_key,
        "game_id": decision.get("game_id"),
        "market": decision.get("market"),
        "entity_id": decision.get("entity_id"),
        "line": decision.get("line"),
        "side": decision.get("side"),
        "status": "RESERVED",
        "reserved_at_utc": current.isoformat(),
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


def finalize_reservation(
    root: str | Path,
    wager_key: str,
    *,
    status: str,
    sportsbook_bet_id: str | None = None,
    now: datetime | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    if status not in {"PLACED", "RELEASED", "FAILED"}:
        raise ExecutionReservationError("INVALID_FINAL_STATUS")
    p = _active_path(root, wager_key)
    if not p.exists():
        raise ExecutionReservationError("RESERVATION_NOT_FOUND")
    current = json.loads(p.read_text(encoding="utf-8"))
    if current.get("status") != "RESERVED":
        raise ExecutionReservationError("RESERVATION_ALREADY_FINALIZED")
    current["status"] = status
    current["finalized_at_utc"] = _utc_now(now).isoformat()
    current["sportsbook_bet_id"] = sportsbook_bet_id
    if detail is not None:
        current["detail"] = str(detail)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return current


def archive_finalized_reservation(
    root: str | Path,
    wager_key: str,
    *,
    now: datetime | None = None,
) -> Path:
    """Move RELEASED/FAILED records out of the active lock namespace.

    PLACED is deliberately never archivable here: a placed wager must continue
    to block duplicate execution for that exact wager_key.
    """
    p = _active_path(root, wager_key)
    if not p.exists():
        raise ExecutionReservationError("RESERVATION_NOT_FOUND")
    record = json.loads(p.read_text(encoding="utf-8"))
    status = str(record.get("status") or "")
    if status == "PLACED":
        raise ExecutionReservationError("PLACED_RESERVATION_CANNOT_ARCHIVE")
    if status not in {"RELEASED", "FAILED"}:
        raise ExecutionReservationError("RESERVATION_NOT_FINALIZED")
    current = _utc_now(now)
    dest = _history_path(root, wager_key, suffix=status.lower(), now=current)
    try:
        os.replace(p, dest)
    except FileNotFoundError as exc:
        raise ExecutionReservationError("RESERVATION_CONCURRENTLY_CHANGED") from exc
    return dest


def recover_stale_reservation(
    root: str | Path,
    wager_key: str,
    *,
    max_age_seconds: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Atomically release a crashed stale RESERVED lock into audit history.

    Recovery is explicit. It never touches PLACED records and never treats a
    non-stale reservation as recoverable.
    """
    if isinstance(max_age_seconds, bool):
        raise ExecutionReservationError("STALE_TTL_INVALID")
    try:
        ttl = float(max_age_seconds)
    except (TypeError, ValueError) as exc:
        raise ExecutionReservationError("STALE_TTL_INVALID") from exc
    if ttl <= 0:
        raise ExecutionReservationError("STALE_TTL_INVALID")

    current = _utc_now(now)
    p = _active_path(root, wager_key)
    if not p.exists():
        raise ExecutionReservationError("RESERVATION_NOT_FOUND")
    record = json.loads(p.read_text(encoding="utf-8"))
    status = str(record.get("status") or "")
    if status == "PLACED":
        raise ExecutionReservationError("PLACED_RESERVATION_NOT_RECOVERABLE")
    if status != "RESERVED":
        raise ExecutionReservationError("RESERVATION_ALREADY_FINALIZED")
    reserved_at = _parse_utc(record.get("reserved_at_utc"))
    age = (current - reserved_at).total_seconds()
    if age < 0:
        raise ExecutionReservationError("RESERVATION_FROM_FUTURE")
    if age <= ttl:
        raise ExecutionReservationError("RESERVATION_NOT_STALE")

    dest = _history_path(root, wager_key, suffix="stale", now=current)
    try:
        os.replace(p, dest)
    except FileNotFoundError as exc:
        raise ExecutionReservationError("RESERVATION_CONCURRENTLY_CHANGED") from exc

    recovered = json.loads(dest.read_text(encoding="utf-8"))
    recovered["status"] = "FAILED"
    recovered["finalized_at_utc"] = current.isoformat()
    recovered["detail"] = "STALE_RESERVATION_RECOVERED"
    recovered["stale_age_seconds"] = age
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(recovered, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, dest)
    return recovered
