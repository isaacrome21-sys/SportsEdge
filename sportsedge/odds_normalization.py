from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Iterable, Mapping

from .mlb_source import GameSnapshot, game_identity, parse_game_start
from .runtime import parse_timestamp


class OddsNormalizationError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedOddsQuote:
    provider_event_id: str
    sportsedge_game_id: str
    mlb_game_pk: int
    bookmaker_key: str
    market: str
    selection: str
    line: float
    american_price: int
    decimal_price: float
    provider_last_update: str
    sportsedge_fetched_at: str


def american_to_decimal(odds: Any) -> float:
    if isinstance(odds, bool):
        raise OddsNormalizationError("american_price must be numeric")
    try:
        value = float(odds)
    except (TypeError, ValueError) as exc:
        raise OddsNormalizationError("american_price must be numeric") from exc
    if not isfinite(value) or (-100 < value < 100):
        raise OddsNormalizationError("invalid American price")
    if value < 0:
        return 1.0 + 100.0 / abs(value)
    return 1.0 + value / 100.0


def _utc(value: Any, field: str) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else parse_timestamp(value)
    except Exception as exc:
        raise OddsNormalizationError(f"{field} invalid") from exc
    if not isinstance(dt, datetime) or dt.tzinfo is None or dt.utcoffset() is None:
        raise OddsNormalizationError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def normalize_quote(*, provider_event_id: Any, game: GameSnapshot, bookmaker_key: Any, market: Any, selection: Any, line: Any, american_price: Any, provider_last_update: Any, sportsedge_fetched_at: Any) -> NormalizedOddsQuote:
    provider_event_id = str(provider_event_id or "").strip()
    bookmaker_key = str(bookmaker_key or "").strip().lower()
    market = str(market or "").strip().upper()
    selection = str(selection or "").strip().upper()
    if not provider_event_id or not bookmaker_key or not market or not selection:
        raise OddsNormalizationError("odds identity incomplete")
    try:
        line_value = float(line)
    except (TypeError, ValueError) as exc:
        raise OddsNormalizationError("line must be numeric") from exc
    if not isfinite(line_value):
        raise OddsNormalizationError("line must be finite")
    decimal = american_to_decimal(american_price)
    american = int(american_price)
    updated = _utc(provider_last_update, "provider_last_update")
    fetched = _utc(sportsedge_fetched_at, "sportsedge_fetched_at")
    if updated > fetched:
        raise OddsNormalizationError("provider_last_update cannot be after sportsedge_fetched_at")
    if fetched >= parse_game_start(game.game_date):
        raise OddsNormalizationError("pregame odds fetched at or after first pitch")
    identity = game_identity(game)
    return NormalizedOddsQuote(
        provider_event_id=provider_event_id,
        sportsedge_game_id=identity.sportsedge_game_id,
        mlb_game_pk=identity.mlb_game_pk,
        bookmaker_key=bookmaker_key,
        market=market,
        selection=selection,
        line=line_value,
        american_price=american,
        decimal_price=decimal,
        provider_last_update=updated.isoformat(),
        sportsedge_fetched_at=fetched.isoformat(),
    )


def dedupe_latest(quotes: Iterable[NormalizedOddsQuote]) -> tuple[NormalizedOddsQuote, ...]:
    latest: dict[tuple[int, str, str, str, float], NormalizedOddsQuote] = {}
    for quote in quotes:
        key = (quote.mlb_game_pk, quote.bookmaker_key, quote.market, quote.selection, quote.line)
        prior = latest.get(key)
        if prior is None:
            latest[key] = quote
            continue
        prior_dt = _utc(prior.provider_last_update, "provider_last_update")
        current_dt = _utc(quote.provider_last_update, "provider_last_update")
        if current_dt > prior_dt:
            latest[key] = quote
        elif current_dt == prior_dt and quote != prior:
            raise OddsNormalizationError("conflicting duplicate odds at identical provider timestamp")
    return tuple(latest[key] for key in sorted(latest))


def quote_to_dict(quote: NormalizedOddsQuote) -> dict[str, Any]:
    return asdict(quote)
