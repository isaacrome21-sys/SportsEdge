"""Best-effort ESPN fallback for MLB full-game moneyline/run-line/total quotes.

This source is intentionally limited to game markets. ESPN's public scoreboard
surface is unofficial and may expose only one partner sportsbook. Every event is
bound back to the MLB StatsAPI schedule before quotes are emitted. The fetched
price is an execution/value input only, never a model feature.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .mlb_source import GameSnapshot, parse_game_start
from .odds_api_source import DEFAULT_TTL_SECONDS, normalize_name

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"


@dataclass(frozen=True)
class ESPNGameOddsSnapshot:
    quotes: tuple[dict[str, Any], ...]
    failures: tuple[dict[str, Any], ...]


def _get_json(url: str, *, opener: Callable = urlopen) -> Mapping[str, Any]:
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge-ESPN-odds/1"})
    with opener(req, timeout=15) as r:
        payload = json.loads(r.read().decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("ESPN_RESPONSE_NOT_OBJECT")
    return payload


def _num(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("ESPN_ODDS_BOOL")
    text = str(value).strip().lower().replace("o", "").replace("u", "")
    return float(text)


def _bind_event(event: Mapping[str, Any], games: list[GameSnapshot]) -> GameSnapshot:
    competitions = event.get("competitions") or []
    if not isinstance(competitions, list) or not competitions:
        raise ValueError("ESPN_COMPETITION_MISSING")
    competition = competitions[0]
    competitors = competition.get("competitors") or []
    by_side = {str(x.get("homeAway")): x for x in competitors if isinstance(x, Mapping)}
    try:
        home_name = str((by_side["home"].get("team") or {}).get("displayName") or "")
        away_name = str((by_side["away"].get("team") or {}).get("displayName") or "")
    except Exception as exc:
        raise ValueError("ESPN_TEAM_IDENTITY_MISSING") from exc
    home_key, away_key = normalize_name(home_name), normalize_name(away_name)
    candidates = [
        g for g in games
        if normalize_name(g.home_name) == home_key and normalize_name(g.away_name) == away_key
    ]
    if not candidates:
        raise ValueError("ESPN_GAME_UNRESOLVED")
    event_time = parse_game_start(str(event.get("date") or ""))
    ranked = sorted((abs((parse_game_start(g.game_date) - event_time).total_seconds()), g) for g in candidates)
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        raise ValueError("ESPN_GAME_AMBIGUOUS")
    if ranked[0][0] > 2 * 60 * 60:
        raise ValueError("ESPN_GAME_TIME_MISMATCH")
    return ranked[0][1]


def _close(node: Mapping[str, Any], side: str) -> Mapping[str, Any]:
    row = node.get(side) or {}
    close = row.get("close") or {}
    if not isinstance(close, Mapping):
        raise ValueError("ESPN_CLOSE_PRICE_MISSING")
    return close


def _base(*, game: GameSnapshot, book: str, fetched_at: datetime, ttl_seconds: int, raw_market: str) -> dict[str, Any]:
    return {
        "game_id": str(game.game_pk),
        "period": "FG",
        "book_key": normalize_name(book) or "espn_partner",
        "sportsbook": book or "ESPN partner",
        "retrieved_at": fetched_at,
        "ttl_seconds": ttl_seconds,
        "raw_market_name": raw_market,
        "away_team": str(game.away_name),
        "home_team": str(game.home_name),
        "is_alternate": False,
        "quote_provider": "ESPN_SCOREBOARD",
        "provider_timestamp_semantics": "FETCH_TIME",
    }


def _parse_event(event: Mapping[str, Any], *, game: GameSnapshot, fetched_at: datetime, ttl_seconds: int) -> ESPNGameOddsSnapshot:
    quotes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    competition = (event.get("competitions") or [None])[0]
    if not isinstance(competition, Mapping):
        return ESPNGameOddsSnapshot((), ({"reason": "ESPN_COMPETITION_MALFORMED", "game_id": str(game.game_pk)},))
    odds_rows = competition.get("odds") or []
    if not isinstance(odds_rows, list) or not odds_rows:
        return ESPNGameOddsSnapshot((), ({"reason": "ESPN_ODDS_MISSING", "game_id": str(game.game_pk)},))

    for odds in odds_rows:
        if not isinstance(odds, Mapping):
            continue
        provider = odds.get("provider") or {}
        book = str(provider.get("displayName") or "ESPN partner") if isinstance(provider, Mapping) else "ESPN partner"
        try:
            ml = odds.get("moneyline") or {}
            for side, team_id, selection in (
                ("home", game.home_id, game.home_name),
                ("away", game.away_id, game.away_name),
            ):
                close = _close(ml, side)
                quotes.append({
                    **_base(game=game, book=book, fetched_at=fetched_at, ttl_seconds=ttl_seconds, raw_market="moneyline"),
                    "market": "MONEYLINE", "entity_id": str(team_id), "side": side.upper(),
                    "selection": str(selection), "line": 0.0, "american_odds": int(_num(close.get("odds"))),
                })
        except Exception as exc:
            failures.append({"reason": f"ESPN_MONEYLINE:{type(exc).__name__}:{exc}", "game_id": str(game.game_pk)})
        try:
            spread = odds.get("pointSpread") or {}
            for side, team_id, selection in (
                ("home", game.home_id, game.home_name),
                ("away", game.away_id, game.away_name),
            ):
                close = _close(spread, side)
                quotes.append({
                    **_base(game=game, book=book, fetched_at=fetched_at, ttl_seconds=ttl_seconds, raw_market="pointSpread"),
                    "market": "RUN_LINE", "entity_id": str(team_id), "side": side.upper(),
                    "selection": str(selection), "line": _num(close.get("line")), "american_odds": int(_num(close.get("odds"))),
                })
        except Exception as exc:
            failures.append({"reason": f"ESPN_RUN_LINE:{type(exc).__name__}:{exc}", "game_id": str(game.game_pk)})
        try:
            total = odds.get("total") or {}
            for side in ("over", "under"):
                close = _close(total, side)
                quotes.append({
                    **_base(game=game, book=book, fetched_at=fetched_at, ttl_seconds=ttl_seconds, raw_market="total"),
                    "market": "TOTALS", "entity_id": str(game.game_pk), "side": side.upper(),
                    "selection": side.title(), "line": _num(close.get("line")), "american_odds": int(_num(close.get("odds"))),
                })
        except Exception as exc:
            failures.append({"reason": f"ESPN_TOTAL:{type(exc).__name__}:{exc}", "game_id": str(game.game_pk)})
    return ESPNGameOddsSnapshot(tuple(quotes), tuple(failures))


def fetch_espn_mlb_game_quotes(
    *,
    schedule: Iterable[GameSnapshot],
    opener: Callable = urlopen,
    now: datetime | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> ESPNGameOddsSnapshot:
    games = list(schedule)
    if not games:
        return ESPNGameOddsSnapshot((), ({"reason": "ESPN_SCHEDULE_EMPTY"},))
    fetched_at = now or datetime.now(timezone.utc)
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_REQUIRED")
    dates = sorted({str(g.official_date or "").replace("-", "") for g in games if g.official_date})
    params = {"dates": ",".join(dates)} if dates else {}
    url = ESPN_SCOREBOARD + ("?" + urlencode(params) if params else "")
    try:
        payload = _get_json(url, opener=opener)
    except Exception as exc:
        return ESPNGameOddsSnapshot((), ({"reason": f"ESPN_PROVIDER:{type(exc).__name__}:{exc}"},))
    events = payload.get("events") or []
    if not isinstance(events, list):
        return ESPNGameOddsSnapshot((), ({"reason": "ESPN_EVENTS_NOT_LIST"},))
    quotes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        try:
            game = _bind_event(event, games)
            snap = _parse_event(event, game=game, fetched_at=fetched_at.astimezone(timezone.utc), ttl_seconds=ttl_seconds)
            quotes.extend(snap.quotes)
            failures.extend(snap.failures)
        except Exception as exc:
            failures.append({"reason": f"{type(exc).__name__}:{exc}", "provider_event_id": str(event.get("id") or "")})
    return ESPNGameOddsSnapshot(tuple(quotes), tuple(failures))
