"""Fail-closed historical NFL prop market binding.

This module normalizes already-persisted decision/close prop snapshots. It does
not fetch, reconstruct, interpolate, or invent historical prices. Two-sided
markets require paired over/under quotes at the identical threshold/book.
ANYTIME_TD may remain one-sided; no-vig market probability is then explicitly
unavailable while offered-price EV may still be evaluated against Model_P.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .prop_engines import MARKETS

CONTRACT = "NFL_PROP_MARKET_HISTORY_V1"


class PropMarketHistoryError(ValueError):
    pass


def _utc(value: Any, reason: str) -> datetime:
    try:
        out = value if isinstance(value, datetime) else datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise PropMarketHistoryError(reason) from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise PropMarketHistoryError(reason)
    return out.astimezone(timezone.utc)


def _text(value: Any, reason: str) -> str:
    out = str(value or "").strip()
    if not out:
        raise PropMarketHistoryError(reason)
    return out


def _price(value: Any, reason: str) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise PropMarketHistoryError(reason) from exc
    if out == 0 or -100 < out < 100:
        raise PropMarketHistoryError(reason)
    return out


def _line(value: Any, reason: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise PropMarketHistoryError(reason) from exc


@dataclass(frozen=True)
class PropMarketSnapshot:
    game_id: str
    player_id: str
    market_id: str
    book: str
    observed_at: str
    game_start: str
    line: float | None
    primary_side: str
    primary_price: int
    opposite_side: str | None
    opposite_price: int | None
    paired_market: bool
    no_vig_available: bool


@dataclass(frozen=True)
class PropDecisionClosePair:
    contract: str
    game_id: str
    player_id: str
    market_id: str
    book: str
    line: float | None
    decision: PropMarketSnapshot
    close: PropMarketSnapshot
    promotion_authority: bool = False
    reconstructed: bool = False


def normalize_prop_snapshot(raw: Mapping[str, Any]) -> PropMarketSnapshot:
    market = _text(raw.get("market_id"), "PROP_HISTORY_MARKET_REQUIRED").upper()
    if market not in MARKETS:
        raise PropMarketHistoryError(f"PROP_HISTORY_MARKET_UNSUPPORTED:{market}")
    game_id = _text(raw.get("game_id"), "PROP_HISTORY_GAME_REQUIRED")
    player_id = _text(raw.get("player_id"), "PROP_HISTORY_PLAYER_REQUIRED")
    book = _text(raw.get("book"), "PROP_HISTORY_BOOK_REQUIRED")
    observed = _utc(raw.get("observed_at"), "PROP_HISTORY_OBSERVED_AT_INVALID")
    start = _utc(raw.get("game_start"), "PROP_HISTORY_GAME_START_INVALID")
    if observed >= start:
        raise PropMarketHistoryError("PROP_HISTORY_POST_START_SNAPSHOT")

    if raw.get("reconstructed") is True or raw.get("backfilled") is True:
        raise PropMarketHistoryError("PROP_HISTORY_RECONSTRUCTED_FORBIDDEN")

    if market == "ANYTIME_TD":
        if raw.get("line") not in (None, ""):
            raise PropMarketHistoryError("PROP_HISTORY_ANYTIME_TD_LINE_FORBIDDEN")
        primary_side = _text(raw.get("primary_side"), "PROP_HISTORY_SIDE_REQUIRED").upper()
        if primary_side not in {"YES", "NO"}:
            raise PropMarketHistoryError("PROP_HISTORY_ANYTIME_TD_SIDE_INVALID")
        opposite = raw.get("opposite_price")
        opposite_price = None if opposite in (None, "") else _price(opposite, "PROP_HISTORY_OPPOSITE_PRICE_INVALID")
        opposite_side = None if opposite_price is None else ("NO" if primary_side == "YES" else "YES")
        paired = opposite_price is not None
        line = None
    else:
        line = _line(raw.get("line"), "PROP_HISTORY_LINE_REQUIRED")
        primary_side = _text(raw.get("primary_side"), "PROP_HISTORY_SIDE_REQUIRED").upper()
        if primary_side not in {"OVER", "UNDER"}:
            raise PropMarketHistoryError("PROP_HISTORY_SIDE_INVALID")
        opposite_price = _price(raw.get("opposite_price"), "PROP_HISTORY_PAIRED_PRICE_REQUIRED")
        opposite_side = "UNDER" if primary_side == "OVER" else "OVER"
        paired = True

    return PropMarketSnapshot(
        game_id=game_id,
        player_id=player_id,
        market_id=market,
        book=book,
        observed_at=observed.isoformat(),
        game_start=start.isoformat(),
        line=line,
        primary_side=primary_side,
        primary_price=_price(raw.get("primary_price"), "PROP_HISTORY_PRIMARY_PRICE_INVALID"),
        opposite_side=opposite_side,
        opposite_price=opposite_price,
        paired_market=paired,
        no_vig_available=paired,
    )


def bind_prop_decision_close(decision_raw: Mapping[str, Any], close_raw: Mapping[str, Any]) -> PropDecisionClosePair:
    decision = normalize_prop_snapshot(decision_raw)
    close = normalize_prop_snapshot(close_raw)
    identity_d = (decision.game_id, decision.player_id, decision.market_id, decision.book)
    identity_c = (close.game_id, close.player_id, close.market_id, close.book)
    if identity_d != identity_c:
        raise PropMarketHistoryError("PROP_HISTORY_IDENTITY_MISMATCH")
    if decision.line != close.line:
        raise PropMarketHistoryError("PROP_HISTORY_THRESHOLD_MISMATCH")
    if decision.primary_side != close.primary_side:
        raise PropMarketHistoryError("PROP_HISTORY_SIDE_MISMATCH")
    if _utc(close.observed_at, "PROP_HISTORY_CLOSE_TIME_INVALID") <= _utc(decision.observed_at, "PROP_HISTORY_DECISION_TIME_INVALID"):
        raise PropMarketHistoryError("PROP_HISTORY_CLOSE_NOT_AFTER_DECISION")
    return PropDecisionClosePair(
        contract=CONTRACT,
        game_id=decision.game_id,
        player_id=decision.player_id,
        market_id=decision.market_id,
        book=decision.book,
        line=decision.line,
        decision=decision,
        close=close,
        promotion_authority=False,
        reconstructed=False,
    )
