"""Keyless direct-DraftKings MLB game-market acquisition.

This source is execution/market context only. It binds DraftKings' web-board event
identity to exactly one MLB StatsAPI game before emitting canonical SportsEdge
quotes. Prices never enter Model_P features. Receipt time is SportsEdge's HTTP
observation time; the direct board does not provide a provider quote timestamp.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
from math import isfinite
from typing import Any, Callable, Iterable, Mapping
from urllib.request import urlopen

from .draftkings_game_market_source import fetch_board, normalize_board
from .mlb_source import GameSnapshot, fetch_schedule
from .odds_api_source import bind_provider_event, normalize_name

SOURCE_CLASS = "DRAFTKINGS_DIRECT_WEB_V1"
BOOK_KEY = "draftkings"
SPORTSBOOK = "DraftKings"
SPORT_KEY = "baseball_mlb"
DEFAULT_TTL_SECONDS = 180
_RAW_MARKETS = {
    "Moneyline": "h2h",
    "Spread": "spreads",
    "Run Line": "spreads",
    "Total": "totals",
}


class DirectDKMLBSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class DirectDKMLBSnapshot:
    quotes: tuple[dict[str, Any], ...]
    failures: tuple[dict[str, Any], ...]
    raw: bytes
    raw_sha256: str
    source_uri: str
    received_at: datetime


def _team_side(name: Any, game: GameSnapshot) -> tuple[str, int]:
    key = normalize_name(name)
    if key == normalize_name(game.home_name):
        return "HOME", int(game.home_id)
    if key == normalize_name(game.away_name):
        return "AWAY", int(game.away_id)
    raise DirectDKMLBSourceError("DIRECT_DK_TEAM_UNRESOLVED")


def _finite_point(value: Any) -> float:
    if isinstance(value, bool):
        raise DirectDKMLBSourceError("DIRECT_DK_LINE_INVALID")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise DirectDKMLBSourceError("DIRECT_DK_LINE_INVALID") from exc
    if not isfinite(out):
        raise DirectDKMLBSourceError("DIRECT_DK_LINE_INVALID")
    return out


def _raw_provider_event(event: Mapping[str, Any]) -> dict[str, Any]:
    event_id = str(event.get("id") or "").strip()
    name = str(event.get("name") or "").strip()
    commence = str(event.get("startEventDate") or "").strip()
    if not event_id or not commence or " @ " not in name:
        raise DirectDKMLBSourceError("DIRECT_DK_EVENT_IDENTITY_INCOMPLETE")
    away, home = (part.strip() for part in name.split(" @ ", 1))
    if not away or not home:
        raise DirectDKMLBSourceError("DIRECT_DK_EVENT_IDENTITY_INCOMPLETE")
    return {
        "id": event_id,
        "home_team": home,
        "away_team": away,
        "commence_time": commence,
    }


def _raw_market_inventory(payload: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], set[tuple[str, str]]]:
    events: dict[str, Mapping[str, Any]] = {}
    for event in payload.get("events") or []:
        if isinstance(event, Mapping) and event.get("id") is not None:
            events[str(event.get("id"))] = event
    present: set[tuple[str, str]] = set()
    for market in payload.get("markets") or []:
        if not isinstance(market, Mapping):
            continue
        canonical = _RAW_MARKETS.get(str(market.get("name") or "").strip())
        event_id = str(market.get("eventId") or "").strip()
        if canonical and event_id:
            present.add((event_id, canonical))
    return events, present


def _validate_pair(market: str, rows: list[Mapping[str, Any]], game: GameSnapshot) -> None:
    if len(rows) != 2:
        raise DirectDKMLBSourceError("DIRECT_DK_MARKET_NOT_EXACTLY_TWO_SIDED")
    outcomes = {str(row.get("outcome") or "") for row in rows}
    if market == "totals":
        if outcomes != {"Over", "Under"}:
            raise DirectDKMLBSourceError("DIRECT_DK_TOTAL_SIDES_INVALID")
        points = [_finite_point(row.get("point")) for row in rows]
        if abs(points[0] - points[1]) > 1e-9:
            raise DirectDKMLBSourceError("DIRECT_DK_TOTAL_LINE_MISMATCH")
        return
    expected = {str(game.home_name), str(game.away_name)}
    if outcomes != expected:
        raise DirectDKMLBSourceError("DIRECT_DK_TEAM_SIDES_INVALID")
    if market == "spreads":
        points = [_finite_point(row.get("point")) for row in rows]
        if abs(points[0] + points[1]) > 1e-9:
            raise DirectDKMLBSourceError("DIRECT_DK_SPREAD_LINE_MISMATCH")


def _quote(
    row: Mapping[str, Any], *, game: GameSnapshot, provider_event: Mapping[str, Any],
    received_at: datetime, raw_sha256: str, source_uri: str, ttl_seconds: int,
) -> dict[str, Any]:
    market = str(row.get("market") or "")
    outcome = str(row.get("outcome") or "")
    base = {
        "game_id": str(game.game_pk),
        "period": "FG",
        "book_key": BOOK_KEY,
        "sportsbook": SPORTSBOOK,
        "retrieved_at": received_at,
        "ttl_seconds": int(ttl_seconds),
        "american_odds": int(row["price_american"]),
        "raw_market_name": f"DK_DIRECT:{market}",
        "is_alternate": False,
        "selection": outcome,
        "source": f"{SOURCE_CLASS};raw_sha256={raw_sha256}",
        "source_url": source_uri,
        "source_provider": SOURCE_CLASS,
        "source_event_id": str(provider_event["id"]),
        "source_home_team_name": str(provider_event["home_team"]),
        "source_away_team_name": str(provider_event["away_team"]),
        "source_identity_version": "DRAFTKINGS_DIRECT_WEB_STATSAPI_BIND_V1",
        "canonical_game_id": str(game.game_pk),
        "canonical_home_team_id": str(game.home_id),
        "canonical_away_team_id": str(game.away_id),
    }
    if market == "h2h":
        side, team_id = _team_side(outcome, game)
        return {
            **base, "market": "MONEYLINE", "entity_id": str(team_id), "side": side,
            "line": 0.0, "offer_id": f"dk-direct:{provider_event['id']}:h2h:{side}",
        }
    if market == "spreads":
        side, team_id = _team_side(outcome, game)
        line = _finite_point(row.get("point"))
        return {
            **base, "market": "RUN_LINE", "entity_id": str(team_id), "side": side,
            "line": line, "offer_id": f"dk-direct:{provider_event['id']}:spreads:{side}:{line}",
        }
    if market == "totals":
        side = outcome.upper()
        if side not in {"OVER", "UNDER"}:
            raise DirectDKMLBSourceError("DIRECT_DK_TOTAL_SIDE_UNSUPPORTED")
        line = _finite_point(row.get("point"))
        return {
            **base, "market": "TOTALS", "entity_id": str(game.game_pk), "side": side,
            "line": line, "offer_id": f"dk-direct:{provider_event['id']}:totals:{side}:{line}",
        }
    raise DirectDKMLBSourceError("DIRECT_DK_MARKET_UNSUPPORTED")


def normalize_direct_dk_mlb_board(
    *, board: Any, schedule: Iterable[GameSnapshot], ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> DirectDKMLBSnapshot:
    if type(ttl_seconds) is not int or ttl_seconds <= 0:
        raise DirectDKMLBSourceError("DIRECT_DK_TTL_INVALID")
    received = board.received_at
    if not isinstance(received, datetime) or received.tzinfo is None or received.utcoffset() is None:
        raise DirectDKMLBSourceError("DIRECT_DK_RECEIPT_TIME_INVALID")
    received = received.astimezone(timezone.utc)
    raw = bytes(board.raw)
    raw_sha = hashlib.sha256(raw).hexdigest()
    payload = board.payload
    if not isinstance(payload, Mapping):
        raise DirectDKMLBSourceError("DIRECT_DK_RESPONSE_SHAPE_INVALID")

    raw_events, present_markets = _raw_market_inventory(payload)
    normalized = normalize_board(board)
    games = list(schedule)
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in normalized:
        event_id = str(row.get("provider_event_id") or "")
        market = str(row.get("market") or "")
        if event_id and market in {"h2h", "spreads", "totals"}:
            grouped.setdefault((event_id, market), []).append(row)

    quotes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    bound: dict[str, tuple[dict[str, Any], GameSnapshot]] = {}
    for event_id in sorted({event_id for event_id, _ in present_markets}):
        try:
            raw_event = raw_events.get(event_id)
            if raw_event is None:
                raise DirectDKMLBSourceError("DIRECT_DK_EVENT_IDENTITY_INCOMPLETE")
            event = _raw_provider_event(raw_event)
            game = bind_provider_event(event, games)
            bound[event_id] = (event, game)
        except Exception as exc:
            failures.append({
                "provider_event_id": event_id,
                "stage": "IDENTITY_BIND",
                "reason": f"{type(exc).__name__}:{exc}",
            })

    seen: set[tuple[str, str, str, str, float, int]] = set()
    for event_id, market in sorted(present_markets):
        if event_id not in bound:
            continue
        event, game = bound[event_id]
        rows = grouped.get((event_id, market), [])
        if not rows:
            failures.append({
                "provider_event_id": event_id,
                "market": market,
                "stage": "MARKET_ADMISSION",
                "reason": "DirectDKMLBSourceError:DIRECT_DK_MARKET_PRESENT_BUT_NOT_ADMISSIBLE",
            })
            continue
        try:
            _validate_pair(market, rows, game)
            pair = [
                _quote(
                    row, game=game, provider_event=event, received_at=received,
                    raw_sha256=raw_sha, source_uri=str(board.source_uri), ttl_seconds=ttl_seconds,
                )
                for row in rows
            ]
            pending: list[tuple[str, str, str, str, float, int]] = []
            for quote in pair:
                identity = (
                    quote["game_id"], quote["market"], quote["entity_id"], quote["side"],
                    float(quote["line"]), int(quote["american_odds"]),
                )
                if identity in seen or identity in pending:
                    raise DirectDKMLBSourceError("DIRECT_DK_DUPLICATE_CANONICAL_QUOTE")
                pending.append(identity)
            seen.update(pending)
            quotes.extend(pair)
        except Exception as exc:
            failures.append({
                "provider_event_id": event_id,
                "market": market,
                "stage": "MARKET_ADMISSION",
                "reason": f"{type(exc).__name__}:{exc}",
            })

    return DirectDKMLBSnapshot(
        quotes=tuple(quotes), failures=tuple(failures), raw=raw, raw_sha256=raw_sha,
        source_uri=str(board.source_uri), received_at=received,
    )


def fetch_mlb_direct_dk_game_quotes(
    *, target_date: date, now: datetime | None = None,
    board_fetcher: Callable[[str], Any] = fetch_board,
    schedule_opener: Callable = urlopen, ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> DirectDKMLBSnapshot:
    current = now or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
        raise DirectDKMLBSourceError("NOW_TIMEZONE_REQUIRED")
    schedule = fetch_schedule(
        target_date.isoformat(), opener=schedule_opener, now=current.astimezone(timezone.utc)
    )
    board = board_fetcher(SPORT_KEY)
    return normalize_direct_dk_mlb_board(board=board, schedule=schedule, ttl_seconds=ttl_seconds)
