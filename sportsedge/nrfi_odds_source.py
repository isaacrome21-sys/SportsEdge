from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping
from urllib.request import urlopen

from .mlb_source import GameSnapshot
from .odds_api_source import (
    DEFAULT_BOOKMAKERS,
    OddsApiSourceError,
    _event_url,
    _get_json,
    bind_provider_event,
)
from .runtime import parse_timestamp

MARKET_KEY = "totals_1st_1_innings"
DEFAULT_TTL_SECONDS = 120


@dataclass(frozen=True)
class FirstInningOddsSnapshot:
    quotes: tuple[dict[str, Any], ...]
    failures: tuple[dict[str, Any], ...]


def parse_first_inning_event_odds(payload: Mapping[str, Any], *, game: GameSnapshot, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> FirstInningOddsSnapshot:
    quotes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for bookmaker in payload.get("bookmakers") or []:
        if not isinstance(bookmaker, Mapping):
            failures.append({"game_id": str(game.game_pk), "reason": "ODDS_BOOKMAKER_MALFORMED"})
            continue
        book_key = str(bookmaker.get("key") or "").strip()
        book_title = str(bookmaker.get("title") or book_key).strip()
        for market in bookmaker.get("markets") or []:
            if not isinstance(market, Mapping) or str(market.get("key") or "") != MARKET_KEY:
                continue
            try:
                updated = parse_timestamp(market.get("last_update") or bookmaker.get("last_update"))
            except Exception:
                failures.append({"game_id": str(game.game_pk), "book_key": book_key, "reason": "NRFI_PRICE_TIMESTAMP_INVALID"})
                continue
            pair: dict[str, Mapping[str, Any]] = {}
            for outcome in market.get("outcomes") or []:
                if not isinstance(outcome, Mapping):
                    continue
                side = str(outcome.get("name") or "").upper()
                if side in {"OVER", "UNDER"}:
                    pair[side] = outcome
            if set(pair) != {"OVER", "UNDER"}:
                failures.append({"game_id": str(game.game_pk), "book_key": book_key, "reason": "NRFI_PRICE_PAIR_INCOMPLETE"})
                continue
            try:
                over_point = float(pair["OVER"].get("point"))
                under_point = float(pair["UNDER"].get("point"))
            except Exception:
                failures.append({"game_id": str(game.game_pk), "book_key": book_key, "reason": "NRFI_PRICE_LINE_INVALID"})
                continue
            if abs(over_point - 0.5) > 1e-12 or abs(under_point - 0.5) > 1e-12:
                failures.append({"game_id": str(game.game_pk), "book_key": book_key, "reason": "NRFI_PRICE_LINE_NOT_0_5", "over_line": over_point, "under_line": under_point})
                continue
            for provider_side, sportsedge_market, sportsedge_side in (
                ("OVER", "YRFI", "YES"),
                ("UNDER", "NRFI", "NO"),
            ):
                outcome = pair[provider_side]
                price = outcome.get("price")
                if price is None:
                    failures.append({"game_id": str(game.game_pk), "book_key": book_key, "reason": "NRFI_PRICE_MISSING", "market": sportsedge_market})
                    continue
                quote = {
                    "game_id": str(game.game_pk),
                    "period": "1ST_INNING",
                    "market": sportsedge_market,
                    "entity_id": str(game.game_pk),
                    "side": sportsedge_side,
                    "line": 0.5,
                    "book_key": book_key,
                    "sportsbook": book_title,
                    "american_odds": price,
                    "retrieved_at": updated,
                    "ttl_seconds": int(ttl_seconds),
                    "raw_market_name": MARKET_KEY,
                }
                if outcome.get("sid") not in (None, ""):
                    quote["offer_id"] = str(outcome["sid"])
                quotes.append(quote)
    return FirstInningOddsSnapshot(tuple(quotes), tuple(failures))


def fetch_first_inning_quotes(*, api_key: str, schedule: Iterable[GameSnapshot], opener: Callable = urlopen, bookmakers: Iterable[str] = DEFAULT_BOOKMAKERS, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> FirstInningOddsSnapshot:
    games = list(schedule)
    events_url = _event_url("/sports/baseball_mlb/events", api_key=api_key)
    events = _get_json(events_url, opener=opener, label="events")
    if not isinstance(events, list):
        raise OddsApiSourceError("ODDS_EVENTS_RESPONSE_NOT_LIST")
    requested_books = ",".join(str(x).strip() for x in bookmakers if str(x).strip())
    if not requested_books:
        raise OddsApiSourceError("ODDS_BOOKMAKERS_MISSING")
    quotes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen_games: set[int] = set()
    for event in events:
        try:
            game = bind_provider_event(event, games)
            if game.game_pk in seen_games:
                raise OddsApiSourceError("NRFI_PROVIDER_DUPLICATE_GAME")
            event_id = str(event.get("id") or "").strip()
            if not event_id:
                raise OddsApiSourceError("ODDS_EVENT_ID_MISSING")
            url = _event_url(
                f"/sports/baseball_mlb/events/{event_id}/odds",
                api_key=api_key,
                params={"bookmakers": requested_books, "markets": MARKET_KEY, "oddsFormat": "american", "dateFormat": "iso", "includeSids": "true"},
            )
            payload = _get_json(url, opener=opener, label="first_inning_event_odds")
            snap = parse_first_inning_event_odds(payload, game=game, ttl_seconds=ttl_seconds)
            quotes.extend(snap.quotes); failures.extend(snap.failures); seen_games.add(game.game_pk)
        except Exception as exc:
            failures.append({"reason": str(exc), "provider_event_id": str(event.get("id") if isinstance(event, Mapping) else "")})
    return FirstInningOddsSnapshot(tuple(quotes), tuple(failures))
