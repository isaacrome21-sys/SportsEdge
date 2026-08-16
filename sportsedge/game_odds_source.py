"""Fail-closed MLB featured-game odds acquisition from The Odds API.

Acquires h2h, spreads and totals and binds every provider event to exactly one
MLB StatsAPI game before emitting SportsEdge quotes. Sportsbook prices are
price/execution inputs only and never Model_P features.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping
from urllib.request import urlopen

from .mlb_source import GameSnapshot
from .odds_api_source import (
    DEFAULT_BOOKMAKERS,
    DEFAULT_TTL_SECONDS,
    OddsApiSourceError,
    _event_url,
    _get_json,
    bind_provider_event,
    normalize_name,
)
from .runtime import parse_timestamp

GAME_MARKETS = ("h2h", "spreads", "totals")


@dataclass(frozen=True)
class GameOddsSnapshot:
    quotes: tuple[dict[str, Any], ...]
    failures: tuple[dict[str, Any], ...]


def _team_side(name: Any, game: GameSnapshot) -> str:
    key = normalize_name(name)
    if key == normalize_name(game.home_name):
        return "HOME"
    if key == normalize_name(game.away_name):
        return "AWAY"
    raise OddsApiSourceError("ODDS_GAME_TEAM_UNRESOLVED")


def _updated(market: Mapping[str, Any], bookmaker: Mapping[str, Any]) -> datetime:
    value = market.get("last_update") or bookmaker.get("last_update")
    try:
        return parse_timestamp(value)
    except Exception as exc:
        raise OddsApiSourceError("ODDS_MARKET_TIMESTAMP_INVALID") from exc


def parse_game_event_odds(payload: Mapping[str, Any], *, game: GameSnapshot, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> GameOddsSnapshot:
    quotes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    if not isinstance(payload, Mapping):
        return GameOddsSnapshot((), ({"reason": "ODDS_EVENT_ODDS_MALFORMED", "game_id": str(game.game_pk)},))
    for bookmaker in payload.get("bookmakers") or []:
        if not isinstance(bookmaker, Mapping):
            failures.append({"reason": "ODDS_BOOKMAKER_MALFORMED", "game_id": str(game.game_pk)})
            continue
        book_key = str(bookmaker.get("key") or "").strip()
        book_title = str(bookmaker.get("title") or book_key).strip()
        for market in bookmaker.get("markets") or []:
            if not isinstance(market, Mapping):
                failures.append({"reason": "ODDS_MARKET_MALFORMED", "game_id": str(game.game_pk), "book_key": book_key})
                continue
            market_key = str(market.get("key") or "").strip()
            if market_key not in GAME_MARKETS:
                continue
            try:
                retrieved_at = _updated(market, bookmaker)
            except Exception as exc:
                failures.append({"reason": str(exc), "game_id": str(game.game_pk), "book_key": book_key, "raw_market_name": market_key})
                continue
            for outcome in market.get("outcomes") or []:
                try:
                    if not isinstance(outcome, Mapping):
                        raise OddsApiSourceError("ODDS_OUTCOME_MALFORMED")
                    price = outcome.get("price")
                    if price is None:
                        raise OddsApiSourceError("ODDS_OUTCOME_PRICE_MISSING")
                    base = {
                        "game_id": str(game.game_pk), "period": "FG", "book_key": book_key,
                        "sportsbook": book_title, "retrieved_at": retrieved_at, "ttl_seconds": ttl_seconds,
                        "american_odds": price, "raw_market_name": market_key,
                        "away_team": str(game.away_name), "home_team": str(game.home_name),
                    }
                    if market_key == "h2h":
                        side = _team_side(outcome.get("name"), game)
                        quotes.append({**base, "market": "MONEYLINE", "side": side, "selection": str(outcome.get("name") or "").strip(), "line": None})
                    elif market_key == "spreads":
                        side = _team_side(outcome.get("name"), game)
                        point = outcome.get("point")
                        if point is None:
                            raise OddsApiSourceError("ODDS_OUTCOME_LINE_MISSING")
                        quotes.append({**base, "market": "RUN_LINE", "side": side, "selection": str(outcome.get("name") or "").strip(), "line": point})
                    else:
                        side = str(outcome.get("name") or "").upper()
                        if side not in {"OVER", "UNDER"}:
                            raise OddsApiSourceError("ODDS_SIDE_UNSUPPORTED")
                        point = outcome.get("point")
                        if point is None:
                            raise OddsApiSourceError("ODDS_OUTCOME_LINE_MISSING")
                        quotes.append({**base, "market": "TOTALS", "side": side, "selection": side.title(), "line": point})
                except Exception as exc:
                    failures.append({"reason": str(exc), "game_id": str(game.game_pk), "book_key": book_key, "raw_market_name": market_key})
    return GameOddsSnapshot(tuple(quotes), tuple(failures))


def fetch_mlb_game_quotes(*, api_key: str, schedule: Iterable[GameSnapshot], opener: Callable = urlopen, bookmakers: Iterable[str] = DEFAULT_BOOKMAKERS, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> GameOddsSnapshot:
    games = list(schedule)
    requested_books = ",".join(str(x).strip() for x in bookmakers if str(x).strip())
    if not requested_books:
        raise OddsApiSourceError("ODDS_BOOKMAKERS_MISSING")
    url = _event_url(
        "/sports/baseball_mlb/odds",
        api_key=api_key,
        params={"regions": "us", "bookmakers": requested_books, "markets": ",".join(GAME_MARKETS), "oddsFormat": "american", "dateFormat": "iso", "includeSids": "true"},
    )
    payload = _get_json(url, opener=opener, label="game-markets")
    if not isinstance(payload, list):
        raise OddsApiSourceError("ODDS_GAME_MARKETS_RESPONSE_NOT_LIST")
    quotes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for event in payload:
        try:
            game = bind_provider_event(event, games)
            snap = parse_game_event_odds(event, game=game, ttl_seconds=ttl_seconds)
            quotes.extend(snap.quotes)
            failures.extend(snap.failures)
        except Exception as exc:
            failures.append({"reason": str(exc), "provider_event_id": str(event.get("id") if isinstance(event, Mapping) else "")})
    return GameOddsSnapshot(tuple(quotes), tuple(failures))
