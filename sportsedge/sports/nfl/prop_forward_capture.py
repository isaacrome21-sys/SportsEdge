"""Fail-closed prospective NFL prop decision/close capture state.

This module never fetches data and never reconstructs missed observations. It
accepts raw provider quotes plus an explicit provider-event kickoff map, then
classifies immutable decision and close observations under frozen windows.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

DECISION_MIN_LEAD_MINUTES = 45
DECISION_MAX_LEAD_MINUTES = 120
CLOSE_MIN_LEAD_MINUTES = 2
CLOSE_MAX_LEAD_MINUTES = 20
CONTRACT = "NFL_PROP_FORWARD_CAPTURE_V1"


class PropForwardCaptureError(ValueError):
    pass


def _utc(value: Any, reason: str) -> datetime:
    try:
        out = value if isinstance(value, datetime) else datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise PropForwardCaptureError(reason) from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise PropForwardCaptureError(reason)
    return out.astimezone(timezone.utc)


def _identity(row: Mapping[str, Any]) -> tuple[str, str, str, str, str, float | None]:
    event_id = str(row.get("provider_event_id") or "").strip()
    player = str(row.get("entity_name_normalized") or "").strip()
    market = str(row.get("market") or "").strip().upper()
    book = str(row.get("book_key") or row.get("sportsbook") or "").strip().lower()
    side = str(row.get("side") or "").strip().upper()
    line_raw = row.get("line")
    line = None if line_raw in (None, "") else float(line_raw)
    if not all((event_id, player, market, book, side)):
        raise PropForwardCaptureError("NFL_PROP_FORWARD_IDENTITY_MISSING")
    return event_id, player, market, book, side, line


def _quote_row(row: Mapping[str, Any], *, captured_at: datetime, game_start: datetime, phase: str) -> dict[str, Any]:
    event_id, player, market, book, side, line = _identity(row)
    try:
        price = int(row.get("american_odds"))
    except (TypeError, ValueError) as exc:
        raise PropForwardCaptureError("NFL_PROP_FORWARD_PRICE_INVALID") from exc
    if price == 0 or -100 < price < 100:
        raise PropForwardCaptureError("NFL_PROP_FORWARD_PRICE_INVALID")
    return {
        "contract": CONTRACT,
        "phase": phase,
        "provider_event_id": event_id,
        "entity_name_normalized": player,
        "entity_name": str(row.get("entity_name") or "").strip(),
        "market": market,
        "book_key": book,
        "side": side,
        "line": line,
        "american_odds": price,
        "captured_at": captured_at.isoformat(),
        "game_start": game_start.isoformat(),
        "provider": str(row.get("provider") or "").strip(),
        "reconstructed": False,
        "backfilled": False,
        "promotion_authority": False,
        "model_p_created": False,
    }


def _keys(rows: Iterable[Mapping[str, Any]]) -> set[tuple[str, str, str, str, str, float | None]]:
    return {_identity(row) for row in rows}


@dataclass(frozen=True)
class CaptureResult:
    decisions: tuple[dict[str, Any], ...]
    closes: tuple[dict[str, Any], ...]
    missed_or_blocked: tuple[dict[str, Any], ...]


def apply_snapshot(
    quotes: Iterable[Mapping[str, Any]],
    *,
    captured_at: Any,
    event_starts: Mapping[str, Any],
    existing_decisions: Iterable[Mapping[str, Any]] = (),
    existing_closes: Iterable[Mapping[str, Any]] = (),
) -> CaptureResult:
    """Classify one raw quote snapshot without reconstructing missed windows.

    A decision is created only at T-120..T-45. A close is created only at
    T-20..T-2 and only for the exact immutable decision identity. Existing
    identities are never overwritten. Missing kickoff identity blocks capture.
    """
    now = _utc(captured_at, "NFL_PROP_FORWARD_CAPTURE_TIME_INVALID")
    decisions = list(dict(row) for row in existing_decisions)
    closes = list(dict(row) for row in existing_closes)
    decision_keys = _keys(decisions)
    close_keys = _keys(closes)
    new_decisions: list[dict[str, Any]] = []
    new_closes: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    for quote in quotes:
        key = _identity(quote)
        event_id = key[0]
        raw_start = event_starts.get(event_id)
        if raw_start in (None, ""):
            blocked.append({"provider_event_id": event_id, "identity": list(key), "reason": "EVENT_START_MISSING"})
            continue
        start = _utc(raw_start, "NFL_PROP_FORWARD_GAME_START_INVALID")
        lead = (start - now).total_seconds() / 60.0
        if lead <= 0:
            blocked.append({"provider_event_id": event_id, "identity": list(key), "reason": "GAME_ALREADY_STARTED"})
            continue

        if key not in decision_keys and DECISION_MIN_LEAD_MINUTES <= lead <= DECISION_MAX_LEAD_MINUTES:
            row = _quote_row(quote, captured_at=now, game_start=start, phase="DECISION")
            new_decisions.append(row)
            decision_keys.add(key)
            continue

        if key in decision_keys and key not in close_keys and CLOSE_MIN_LEAD_MINUTES <= lead <= CLOSE_MAX_LEAD_MINUTES:
            row = _quote_row(quote, captured_at=now, game_start=start, phase="CLOSE")
            new_closes.append(row)
            close_keys.add(key)
            continue

        if key not in decision_keys and lead < DECISION_MIN_LEAD_MINUTES:
            blocked.append({"provider_event_id": event_id, "identity": list(key), "reason": "MISSED_DECISION_WINDOW_NO_BACKFILL"})

    return CaptureResult(tuple(new_decisions), tuple(new_closes), tuple(blocked))
