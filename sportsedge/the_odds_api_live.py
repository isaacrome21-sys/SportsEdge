"""Provider-neutral current/live market adapter for The Odds API.

This module is intentionally market-only. Prices may bind SportsEdge decisions,
but never become Model_P features. It supports current boards and historical
snapshots so RUN IT can preserve an auditable quote trail.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import urlopen

from .market_data_contract import MarketDataContractError, MarketQuote, canonical_json_sha256

BASE_URL = "https://api.the-odds-api.com/v4"
DEFAULT_MARKETS = ("h2h", "spreads", "totals")
DEFAULT_REGIONS = ("us",)


class TheOddsApiError(RuntimeError):
    pass


def _parse_time(value: Any, *, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise TheOddsApiError(f"{field}_MISSING")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise TheOddsApiError(f"{field}_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TheOddsApiError(f"{field}_TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def build_current_odds_url(
    *,
    api_key: str,
    sport_key: str,
    markets: Iterable[str] = DEFAULT_MARKETS,
    regions: Iterable[str] = DEFAULT_REGIONS,
    bookmakers: Iterable[str] = (),
) -> str:
    if not api_key.strip():
        raise TheOddsApiError("API_KEY_REQUIRED")
    if not sport_key.strip():
        raise TheOddsApiError("SPORT_KEY_REQUIRED")
    params = {
        "apiKey": api_key,
        "regions": ",".join(x.strip() for x in regions if x.strip()),
        "markets": ",".join(x.strip() for x in markets if x.strip()),
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    books = ",".join(x.strip() for x in bookmakers if x.strip())
    if books:
        params["bookmakers"] = books
    return f"{BASE_URL}/sports/{sport_key}/odds?{urlencode(params)}"


def build_historical_odds_url(
    *,
    api_key: str,
    sport_key: str,
    at: datetime,
    markets: Iterable[str] = DEFAULT_MARKETS,
    regions: Iterable[str] = DEFAULT_REGIONS,
    bookmakers: Iterable[str] = (),
) -> str:
    if at.tzinfo is None or at.utcoffset() is None:
        raise TheOddsApiError("HISTORICAL_AT_TIMEZONE_REQUIRED")
    params = {
        "apiKey": api_key,
        "regions": ",".join(x.strip() for x in regions if x.strip()),
        "markets": ",".join(x.strip() for x in markets if x.strip()),
        "oddsFormat": "american",
        "dateFormat": "iso",
        "date": at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    books = ",".join(x.strip() for x in bookmakers if x.strip())
    if books:
        params["bookmakers"] = books
    return f"{BASE_URL}/historical/sports/{sport_key}/odds?{urlencode(params)}"


def _get_json(url: str, *, opener: Callable = urlopen) -> Any:
    try:
        with opener(url, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise TheOddsApiError(f"PROVIDER_FETCH_FAILED:{type(exc).__name__}:{exc}") from exc


def normalize_event(
    event: Mapping[str, Any],
    *,
    sport_key: str,
    captured_at: datetime,
) -> tuple[MarketQuote, ...]:
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise TheOddsApiError("CAPTURED_AT_TIMEZONE_REQUIRED")
    captured_at = captured_at.astimezone(timezone.utc)
    provider_event_id = str(event.get("id") or "").strip()
    if not provider_event_id:
        raise TheOddsApiError("PROVIDER_EVENT_ID_MISSING")
    commence = _parse_time(event.get("commence_time"), field="COMMENCE_TIME")
    in_play = commence <= captured_at
    raw_sha = canonical_json_sha256(event)
    home = str(event.get("home_team") or "").strip() or None
    away = str(event.get("away_team") or "").strip() or None
    quotes: list[MarketQuote] = []
    for book in event.get("bookmakers") or []:
        if not isinstance(book, Mapping):
            continue
        book_key = str(book.get("key") or book.get("title") or "").strip()
        for market in book.get("markets") or []:
            if not isinstance(market, Mapping):
                continue
            market_key = str(market.get("key") or "").strip()
            updated_raw = market.get("last_update") or book.get("last_update")
            updated = _parse_time(updated_raw, field="PROVIDER_UPDATED_AT")
            for outcome in market.get("outcomes") or []:
                if not isinstance(outcome, Mapping):
                    continue
                selection = str(outcome.get("name") or "").strip()
                if not selection:
                    continue
                try:
                    price = int(outcome.get("price"))
                except (TypeError, ValueError) as exc:
                    raise TheOddsApiError("AMERICAN_ODDS_INVALID") from exc
                point_raw = outcome.get("point")
                point = None if point_raw is None else float(point_raw)
                quotes.append(
                    MarketQuote(
                        provider="THE_ODDS_API",
                        book=book_key,
                        sport_key=sport_key,
                        provider_event_id=provider_event_id,
                        market=market_key,
                        selection=selection,
                        american_odds=price,
                        point=point,
                        captured_at=captured_at,
                        provider_updated_at=updated,
                        raw_payload_sha256=raw_sha,
                        home_team=home,
                        away_team=away,
                        commence_time=commence,
                        in_play=in_play,
                    )
                )
    return tuple(quotes)


def normalize_response(
    payload: Any,
    *,
    sport_key: str,
    captured_at: datetime,
) -> tuple[MarketQuote, ...]:
    if isinstance(payload, Mapping) and "data" in payload:
        payload = payload.get("data")
    if not isinstance(payload, list):
        raise TheOddsApiError("ODDS_RESPONSE_NOT_LIST")
    out: list[MarketQuote] = []
    for event in payload:
        if isinstance(event, Mapping):
            out.extend(normalize_event(event, sport_key=sport_key, captured_at=captured_at))
    return tuple(out)


def fetch_current_quotes(
    *,
    api_key: str,
    sport_key: str,
    markets: Iterable[str] = DEFAULT_MARKETS,
    regions: Iterable[str] = DEFAULT_REGIONS,
    bookmakers: Iterable[str] = (),
    captured_at: datetime | None = None,
    opener: Callable = urlopen,
) -> tuple[MarketQuote, ...]:
    now = captured_at or datetime.now(timezone.utc)
    url = build_current_odds_url(
        api_key=api_key,
        sport_key=sport_key,
        markets=markets,
        regions=regions,
        bookmakers=bookmakers,
    )
    return normalize_response(_get_json(url, opener=opener), sport_key=sport_key, captured_at=now)


def fetch_historical_quotes(
    *,
    api_key: str,
    sport_key: str,
    at: datetime,
    markets: Iterable[str] = DEFAULT_MARKETS,
    regions: Iterable[str] = DEFAULT_REGIONS,
    bookmakers: Iterable[str] = (),
    captured_at: datetime | None = None,
    opener: Callable = urlopen,
) -> tuple[MarketQuote, ...]:
    now = captured_at or datetime.now(timezone.utc)
    url = build_historical_odds_url(
        api_key=api_key,
        sport_key=sport_key,
        at=at,
        markets=markets,
        regions=regions,
        bookmakers=bookmakers,
    )
    return normalize_response(_get_json(url, opener=opener), sport_key=sport_key, captured_at=now)
