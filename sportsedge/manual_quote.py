from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any, Mapping

from .runtime import parse_timestamp


class ManualQuoteError(ValueError):
    pass


@dataclass(frozen=True)
class ManualQuote:
    game_id: str
    market_type: str
    side: str
    line: float
    price: int
    paired_side: str
    paired_price: int
    book: str
    observed_at: datetime
    first_pitch_at: datetime
    source: str
    subject_id: str | None = None


def _text(value: Any, name: str) -> str:
    out = str(value or "").strip()
    if not out:
        raise ManualQuoteError(f"{name} is required")
    return out


def _line(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ManualQuoteError("line must be numeric") from exc
    if not isfinite(out):
        raise ManualQuoteError("line must be finite")
    return out


def _price(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ManualQuoteError(f"{name} must be American odds")
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise ManualQuoteError(f"{name} must be American odds") from exc
    if out == 0 or -100 < out < 100:
        raise ManualQuoteError(f"{name} must be <= -100 or >= 100")
    return out


def validate_manual_quote(raw: Mapping[str, Any]) -> ManualQuote:
    if not isinstance(raw, Mapping):
        raise ManualQuoteError("manual quote must be an object")
    observed = parse_timestamp(_text(raw.get("observed_at"), "observed_at"))
    first_pitch = parse_timestamp(_text(raw.get("first_pitch_at"), "first_pitch_at"))
    if observed >= first_pitch:
        raise ManualQuoteError("MANUAL_QUOTE_NOT_PREGAME")
    side = _text(raw.get("side"), "side").upper()
    paired_side = _text(raw.get("paired_side"), "paired_side").upper()
    if side == paired_side:
        raise ManualQuoteError("paired_side must differ from side")
    source = _text(raw.get("source", "MANUAL"), "source").upper()
    if source != "MANUAL":
        raise ManualQuoteError("manual lane requires source=MANUAL")
    subject = raw.get("subject_id")
    return ManualQuote(
        game_id=_text(raw.get("game_id"), "game_id"),
        market_type=_text(raw.get("market_type"), "market_type").upper(),
        side=side,
        line=_line(raw.get("line")),
        price=_price(raw.get("price"), "price"),
        paired_side=paired_side,
        paired_price=_price(raw.get("paired_price"), "paired_price"),
        book=_text(raw.get("book"), "book").lower(),
        observed_at=observed,
        first_pitch_at=first_pitch,
        source=source,
        subject_id=None if subject in (None, "") else str(subject),
    )
