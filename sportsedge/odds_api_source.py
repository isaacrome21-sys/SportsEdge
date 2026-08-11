"""Native MLB player-prop quote acquisition from The Odds API.

Provider event IDs and player names are never trusted as MLB identity: every
event must bind uniquely to a StatsAPI schedule game and every player description
must bind uniquely to an MLB player id for that exact game.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import unicodedata
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .mlb_source import GameSnapshot, parse_game_start
from .runtime import parse_timestamp

BASE = "https://api.the-odds-api.com/v4"
SPORT_KEY = "baseball_mlb"
DEFAULT_BOOKMAKERS = ("draftkings",)
DEFAULT_TTL_SECONDS = 300
EVENT_TIME_TOLERANCE_SECONDS = 90 * 60

MARKETS = {
    "batter_hits": ("HITS", False),
    "batter_hits_alternate": ("HITS", True),
    "batter_total_bases": ("TOTAL_BASES", False),
    "batter_total_bases_alternate": ("TOTAL_BASES", True),
    "pitcher_walks": ("PITCHER_BB", False),
    "pitcher_walks_alternate": ("PITCHER_BB", True),
}


class OddsApiSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class OddsApiSnapshot:
    quotes: tuple[dict[str, Any], ...]
    failures: tuple[dict[str, Any], ...]


def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return "".join(ch.lower() for ch in text if ch.isalnum())


def _get_json(url: str, *, opener: Callable = urlopen, label: str) -> Any:
    try:
        with opener(Request(url, headers={"Accept": "application/json"}), timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise OddsApiSourceError(f"ODDS_API_FETCH_FAILED:{label}") from exc


def _event_url(path: str, *, api_key: str, params: Mapping[str, Any] | None = None) -> str:
    if not isinstance(api_key, str) or not api_key.strip():
        raise OddsApiSourceError("ODDS_API_KEY_MISSING")
    query = {"apiKey": api_key.strip(), **dict(params or {})}
    return f"{BASE}{path}?{urlencode(query)}"


def _provider_time(value: Any) -> datetime:
    try:
        dt = parse_timestamp(value)
    except Exception as exc:
        raise OddsApiSourceError("ODDS_EVENT_TIME_INVALID") from exc
    return dt.astimezone(timezone.utc)


def bind_provider_event(event: Mapping[str, Any], schedule: Iterable[GameSnapshot]) -> GameSnapshot:
    if not isinstance(event, Mapping):
        raise OddsApiSourceError("ODDS_EVENT_MALFORMED")
    home = normalize_name(event.get("home_team"))
    away = normalize_name(event.get("away_team"))
    if not home or not away:
        raise OddsApiSourceError("ODDS_EVENT_TEAM_IDENTITY_MISSING")
    commence = _provider_time(event.get("commence_time"))
    team_matches = [g for g in schedule if normalize_name(g.home_name) == home and normalize_name(g.away_name) == away]
    timed = [g for g in team_matches if abs((parse_game_start(g.game_date) - commence).total_seconds()) <= EVENT_TIME_TOLERANCE_SECONDS]
    if len(timed) != 1:
        raise OddsApiSourceError("ODDS_EVENT_GAME_NOT_FOUND" if not timed else "ODDS_EVENT_GAME_AMBIGUOUS")
    return timed[0]


def build_participant_index(
    *,
    schedule: Iterable[GameSnapshot],
    confirmed_names_by_game: Mapping[int, Iterable[tuple[int, str]]],
    projected_names_by_game: Mapping[int, Iterable[tuple[int, str]]] | None = None,
) -> dict[int, dict[str, int]]:
    projected_names_by_game = projected_names_by_game or {}
    out: dict[int, dict[str, int]] = {}
    for game in schedule:
        candidates: list[tuple[int, str]] = []
        candidates.extend(list(confirmed_names_by_game.get(game.game_pk, ())))
        candidates.extend(list(projected_names_by_game.get(game.game_pk, ())))
        for pid, name in (
            (game.away_probable_pitcher_id, game.away_probable_pitcher_name),
            (game.home_probable_pitcher_id, game.home_probable_pitcher_name),
        ):
            if pid is not None and name:
                candidates.append((int(pid), str(name)))
        idx: dict[str, int] = {}
        ambiguous: set[str] = set()
        for player_id, name in candidates:
            key = normalize_name(name)
            if not key or int(player_id) <= 0:
                continue
            prior = idx.get(key)
            if prior is not None and prior != int(player_id):
                ambiguous.add(key)
            else:
                idx[key] = int(player_id)
        for key in ambiguous:
            idx.pop(key, None)
        out[game.game_pk] = idx
    return out


def _participant_id(description: Any, *, game_pk: int, participant_index: Mapping[int, Mapping[str, int]]) -> int:
    name = normalize_name(description)
    if not name:
        raise OddsApiSourceError("ODDS_PLAYER_NAME_MISSING")
    player_id = (participant_index.get(int(game_pk)) or {}).get(name)
    if not isinstance(player_id, int) or player_id <= 0:
        raise OddsApiSourceError("ODDS_PLAYER_ID_UNRESOLVED")
    return player_id


def parse_event_odds(
    payload: Mapping[str, Any],
    *,
    game: GameSnapshot,
    participant_index: Mapping[int, Mapping[str, int]],
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> OddsApiSnapshot:
    quotes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    if not isinstance(payload, Mapping):
        return OddsApiSnapshot((), ({"reason": "ODDS_EVENT_ODDS_MALFORMED", "game_id": str(game.game_pk)},))
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
            mapped = MARKETS.get(market_key)
            if mapped is None:
                continue
            sportsedge_market, alternate = mapped
            updated = market.get("last_update") or bookmaker.get("last_update")
            try:
                retrieved_at = parse_timestamp(updated)
            except Exception:
                failures.append({"reason": "ODDS_MARKET_TIMESTAMP_INVALID", "game_id": str(game.game_pk), "book_key": book_key, "raw_market_name": market_key})
                continue
            for outcome in market.get("outcomes") or []:
                try:
                    if not isinstance(outcome, Mapping):
                        raise OddsApiSourceError("ODDS_OUTCOME_MALFORMED")
                    side = str(outcome.get("name") or "").upper()
                    if side not in {"OVER", "UNDER"}:
                        raise OddsApiSourceError("ODDS_SIDE_UNSUPPORTED")
                    player_id = _participant_id(outcome.get("description"), game_pk=game.game_pk, participant_index=participant_index)
                    point = outcome.get("point")
                    price = outcome.get("price")
                    if point is None or price is None:
                        raise OddsApiSourceError("ODDS_OUTCOME_PRICE_IDENTITY_MISSING")
                    quote = {
                        "game_id": str(game.game_pk),
                        "period": "FG",
                        "market": sportsedge_market,
                        "entity_id": str(player_id),
                        "side": side,
                        "line": point,
                        "book_key": book_key,
                        "retrieved_at": retrieved_at,
                        "is_alternate": alternate,
                        "raw_market_name": market_key,
                        "american_odds": price,
                        "ttl_seconds": ttl_seconds,
                        "sportsbook": book_title,
                    }
                    if outcome.get("sid") not in (None, ""):
                        quote["offer_id"] = str(outcome["sid"])
                    quotes.append(quote)
                except Exception as exc:
                    failures.append({
                        "reason": str(exc),
                        "game_id": str(game.game_pk),
                        "book_key": book_key,
                        "raw_market_name": market_key,
                        "player_name": str(outcome.get("description") if isinstance(outcome, Mapping) else ""),
                    })
    return OddsApiSnapshot(tuple(quotes), tuple(failures))


def fetch_mlb_player_prop_quotes(
    *,
    api_key: str,
    schedule: Iterable[GameSnapshot],
    participant_index: Mapping[int, Mapping[str, int]],
    opener: Callable = urlopen,
    bookmakers: Iterable[str] = DEFAULT_BOOKMAKERS,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> OddsApiSnapshot:
    games = list(schedule)
    events_url = _event_url(f"/sports/{SPORT_KEY}/events", api_key=api_key)
    events = _get_json(events_url, opener=opener, label="events")
    if not isinstance(events, list):
        raise OddsApiSourceError("ODDS_EVENTS_RESPONSE_NOT_LIST")
    quotes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    requested_markets = ",".join(MARKETS)
    requested_books = ",".join(str(x).strip() for x in bookmakers if str(x).strip())
    if not requested_books:
        raise OddsApiSourceError("ODDS_BOOKMAKERS_MISSING")
    for event in events:
        try:
            game = bind_provider_event(event, games)
            event_id = str(event.get("id") or "").strip()
            if not event_id:
                raise OddsApiSourceError("ODDS_EVENT_ID_MISSING")
            url = _event_url(
                f"/sports/{SPORT_KEY}/events/{event_id}/odds",
                api_key=api_key,
                params={
                    "bookmakers": requested_books,
                    "markets": requested_markets,
                    "oddsFormat": "american",
                    "dateFormat": "iso",
                    "includeSids": "true",
                },
            )
            snapshot = parse_event_odds(
                _get_json(url, opener=opener, label=f"event:{event_id}"),
                game=game,
                participant_index=participant_index,
                ttl_seconds=ttl_seconds,
            )
            quotes.extend(snapshot.quotes)
            failures.extend(snapshot.failures)
        except Exception as exc:
            failures.append({"reason": str(exc), "provider_event_id": str(event.get("id") if isinstance(event, Mapping) else "")})
    return OddsApiSnapshot(tuple(quotes), tuple(failures))
