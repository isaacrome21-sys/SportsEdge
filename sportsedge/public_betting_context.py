"""Public betting / ticket-handle context normalization.

These signals are context-only. They may annotate RUN IT market microstructure,
but cannot create or modify SportsEdge Model_P, promotion, staking, or OFFICIAL
authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .market_data_contract import PublicBettingSplit, canonical_json_sha256


class PublicBettingContextError(ValueError):
    pass


def _pct(value: Any, *, field: str) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.strip().replace("%", "")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise PublicBettingContextError(f"{field}_INVALID") from exc
    if not 0.0 <= parsed <= 100.0:
        raise PublicBettingContextError(f"{field}_OUT_OF_RANGE")
    return parsed


def normalize_split_row(
    row: Mapping[str, Any],
    *,
    source: str,
    sport_key: str,
    captured_at: datetime,
    raw_payload: Any | None = None,
) -> PublicBettingSplit:
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise PublicBettingContextError("CAPTURED_AT_TIMEZONE_REQUIRED")
    event_key = str(row.get("event_key") or row.get("event_id") or "").strip()
    market = str(row.get("market") or "").strip().upper()
    selection = str(row.get("selection") or row.get("side") or "").strip()
    if not event_key:
        raise PublicBettingContextError("EVENT_KEY_REQUIRED")
    if not market:
        raise PublicBettingContextError("MARKET_REQUIRED")
    if not selection:
        raise PublicBettingContextError("SELECTION_REQUIRED")
    source_updated = row.get("source_updated_at")
    if source_updated is not None:
        if isinstance(source_updated, str):
            text = source_updated.strip().replace("Z", "+00:00")
            source_updated = datetime.fromisoformat(text)
        if source_updated.tzinfo is None or source_updated.utcoffset() is None:
            raise PublicBettingContextError("SOURCE_UPDATED_AT_TIMEZONE_REQUIRED")
        source_updated = source_updated.astimezone(timezone.utc)
    raw_sha = canonical_json_sha256(raw_payload if raw_payload is not None else row)
    return PublicBettingSplit(
        source=source,
        sport_key=sport_key,
        event_key=event_key,
        market=market,
        selection=selection,
        ticket_percent=_pct(row.get("ticket_percent", row.get("bets_percent")), field="TICKET_PERCENT"),
        money_percent=_pct(row.get("money_percent", row.get("handle_percent")), field="MONEY_PERCENT"),
        captured_at=captured_at.astimezone(timezone.utc),
        source_updated_at=source_updated,
        raw_payload_sha256=raw_sha,
    )


def normalize_split_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    source: str,
    sport_key: str,
    captured_at: datetime,
    raw_payload: Any | None = None,
) -> tuple[PublicBettingSplit, ...]:
    return tuple(
        normalize_split_row(
            row,
            source=source,
            sport_key=sport_key,
            captured_at=captured_at,
            raw_payload=raw_payload if raw_payload is not None else row,
        )
        for row in rows
    )


def divergence_label(split: PublicBettingSplit) -> str:
    gap = split.money_ticket_divergence
    if gap is None:
        return "INCOMPLETE_SPLIT"
    magnitude = abs(gap)
    if magnitude >= 20.0:
        return "EXTREME_DIVERGENCE"
    if magnitude >= 10.0:
        return "STRONG_DIVERGENCE"
    if magnitude >= 5.0:
        return "MODERATE_DIVERGENCE"
    return "LOW_DIVERGENCE"


def context_payload(split: PublicBettingSplit) -> dict[str, Any]:
    payload = split.as_context_dict()
    payload["divergence_label"] = divergence_label(split)
    payload["capper_vote"] = False
    payload["model_p_input"] = False
    payload["truth_gate_input"] = False
    return payload
