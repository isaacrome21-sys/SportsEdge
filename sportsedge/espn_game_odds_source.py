"""Credential-free DraftKings MLB game prices exposed through ESPN's web header.

This is a FALLBACK for full-game MONEYLINE/RUN_LINE/TOTALS only. ESPN does not
publish a sportsbook last-update timestamp in this payload, so ``retrieved_at``
is explicitly the SportsEdge HTTP retrieval time and the fallback uses a short
fetch-age TTL. It must never be represented as a DraftKings update timestamp.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .mlb_source import GameSnapshot, parse_game_start
from .odds_api_source import EVENT_TIME_TOLERANCE_SECONDS, normalize_name

BASE = "https://site.web.api.espn.com/apis/v2/scoreboard/header"
SOURCE_NAME = "ESPN_WEB_HEADER_DRAFTKINGS"
BOOK_KEY = "draftkings"
BOOK_TITLE = "DraftKings"
# This source carries fetch-time freshness rather than provider-update freshness.
# Keep its TTL materially tighter than the primary feed's 300 seconds.
DEFAULT_TTL_SECONDS = 60


class EspnGameOddsError(RuntimeError):
    pass


@dataclass(frozen=True)
class EspnGameOddsSnapshot:
    quotes: tuple[dict[str, Any], ...]
    failures: tuple[dict[str, Any], ...]


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise EspnGameOddsError("ESPN_RETRIEVED_AT_TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc)


def _american(value: Any) -> int:
    if isinstance(value, bool):
        raise EspnGameOddsError("ESPN_ODDS_INVALID")
    try:
        out = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise EspnGameOddsError("ESPN_ODDS_INVALID") from exc
    if out == 0 or -100 < out < 100:
        raise EspnGameOddsError("ESPN_ODDS_INVALID")
    return out


def _line(value: Any) -> float:
    if isinstance(value, bool):
        raise EspnGameOddsError("ESPN_LINE_INVALID")
    text = str(value or "").strip().lower()
    if text in {"", "off"}:
        raise EspnGameOddsError("ESPN_LINE_UNAVAILABLE")
    if text[0:1] in {"o", "u"}:
        text = text[1:]
    try:
        return float(text)
    except (TypeError, ValueError) as exc:
        raise EspnGameOddsError("ESPN_LINE_INVALID") from exc


def _event_team_names(event: Mapping[str, Any]) -> tuple[str, str]:
    """Extract exact home/away team labels from the ESPN header event shape.

    The web-header endpoint exposes competitors directly on the event (not under
    a competitions wrapper). Require exactly two structured competitors and one
    unambiguous home + away designation; never infer sides from event-name order.
    """
    competitors = event.get("competitors") or []
    if not isinstance(competitors, list) or len(competitors) != 2:
        raise EspnGameOddsError("ESPN_COMPETITOR_IDENTITY_INVALID")
    away = home = ""
    for row in competitors:
        if not isinstance(row, Mapping):
            raise EspnGameOddsError("ESPN_COMPETITOR_IDENTITY_INVALID")
        name = str(row.get("displayName") or "").strip()
        side = str(row.get("homeAway") or "").lower()
        if not name or side not in {"home", "away"}:
            raise EspnGameOddsError("ESPN_TEAM_IDENTITY_MISSING")
        if side == "away":
            if away: raise EspnGameOddsError("ESPN_TEAM_IDENTITY_AMBIGUOUS")
            away = name
        else:
            if home: raise EspnGameOddsError("ESPN_TEAM_IDENTITY_AMBIGUOUS")
            home = name
    if not away or not home:
        raise EspnGameOddsError("ESPN_TEAM_IDENTITY_MISSING")
    return away, home


def bind_espn_event(event: Mapping[str, Any], schedule: Iterable[GameSnapshot]) -> GameSnapshot:
    if not isinstance(event, Mapping):
        raise EspnGameOddsError("ESPN_EVENT_MALFORMED")
    if str(event.get("status") or "").lower() != "pre":
        raise EspnGameOddsError("ESPN_EVENT_NOT_PREGAME")
    away, home = _event_team_names(event)
    raw_date = event.get("date")
    try:
        start = parse_game_start(raw_date)
    except Exception as exc:
        raise EspnGameOddsError("ESPN_EVENT_TIME_INVALID") from exc
    matches = [
        g for g in schedule
        if g.status == "Preview"
        and normalize_name(g.away_name) == normalize_name(away)
        and normalize_name(g.home_name) == normalize_name(home)
        and abs((parse_game_start(g.game_date) - start).total_seconds()) <= EVENT_TIME_TOLERANCE_SECONDS
    ]
    if len(matches) != 1:
        raise EspnGameOddsError("ESPN_EVENT_GAME_NOT_FOUND" if not matches else "ESPN_EVENT_GAME_AMBIGUOUS")
    return matches[0]


def _runline_side(point_spread: Mapping[str, Any], side: str) -> tuple[float, int]:
    row = point_spread.get(side) or {}
    if not isinstance(row, Mapping):
        raise EspnGameOddsError("ESPN_RUNLINE_SIDE_MISSING")
    # ESPN labels the actively displayed pregame value as ``close`` in this
    # endpoint. Never fall back to ``open``: that could manufacture a stale line.
    displayed = row.get("close") or {}
    if not isinstance(displayed, Mapping):
        raise EspnGameOddsError("ESPN_RUNLINE_CURRENT_MISSING")
    return _line(displayed.get("line")), _american(displayed.get("odds"))


def parse_espn_event_odds(
    event: Mapping[str, Any], *, game: GameSnapshot, retrieved_at: datetime,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> EspnGameOddsSnapshot:
    retrieved = _aware_utc(retrieved_at)
    if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or ttl_seconds <= 0 or ttl_seconds > DEFAULT_TTL_SECONDS:
        raise EspnGameOddsError("ESPN_FALLBACK_TTL_INVALID")
    if str(event.get("status") or "").lower() != "pre":
        raise EspnGameOddsError("ESPN_EVENT_NOT_PREGAME")
    odds = event.get("odds") or {}
    if not isinstance(odds, Mapping):
        raise EspnGameOddsError("ESPN_ODDS_MISSING")
    provider = str(((odds.get("provider") or {}).get("name")) or "").strip()
    if provider != BOOK_TITLE:
        raise EspnGameOddsError("ESPN_PROVIDER_NOT_DRAFTKINGS")

    base = {
        "game_id": str(game.game_pk), "period": "FG", "entity_id": "",
        "book_key": BOOK_KEY, "sportsbook": BOOK_TITLE, "retrieved_at": retrieved,
        "ttl_seconds": ttl_seconds, "is_alternate": False,
        "source_url": SOURCE_NAME,
    }
    failures: list[dict[str, Any]] = []
    quotes: list[dict[str, Any]] = []

    for side, key, selection in (("HOME", "home", game.home_name), ("AWAY", "away", game.away_name)):
        try:
            row = odds.get(key) or {}
            price = _american(row.get("moneyLine") if isinstance(row, Mapping) else None)
            quotes.append({**base, "market": "MONEYLINE", "side": side, "selection": selection,
                           "line": None, "american_odds": price, "raw_market_name": "espn_dk_moneyline"})
        except Exception as exc:
            failures.append({"game_id": str(game.game_pk), "market": "MONEYLINE", "side": side, "reason": str(exc)})

    point_spread = odds.get("pointSpread") or {}
    if isinstance(point_spread, Mapping):
        for side, key, selection in (("HOME", "home", game.home_name), ("AWAY", "away", game.away_name)):
            try:
                point, price = _runline_side(point_spread, key)
                quotes.append({**base, "market": "RUN_LINE", "side": side, "selection": selection,
                               "line": point, "american_odds": price, "raw_market_name": "espn_dk_runline"})
            except Exception as exc:
                failures.append({"game_id": str(game.game_pk), "market": "RUN_LINE", "side": side, "reason": str(exc)})
    else:
        failures.append({"game_id": str(game.game_pk), "market": "RUN_LINE", "reason": "ESPN_RUNLINE_MISSING"})

    try:
        total = _line(odds.get("overUnder"))
        over = _american(odds.get("overOdds")); under = _american(odds.get("underOdds"))
        quotes.extend((
            {**base, "market": "TOTALS", "side": "OVER", "selection": "Over", "line": total,
             "american_odds": over, "raw_market_name": "espn_dk_total"},
            {**base, "market": "TOTALS", "side": "UNDER", "selection": "Under", "line": total,
             "american_odds": under, "raw_market_name": "espn_dk_total"},
        ))
    except Exception as exc:
        failures.append({"game_id": str(game.game_pk), "market": "TOTALS", "reason": str(exc)})

    return EspnGameOddsSnapshot(tuple(quotes), tuple(failures))


def _extract_mlb_events(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = []
    for sport in payload.get("sports") or []:
        if not isinstance(sport, Mapping): continue
        for league in sport.get("leagues") or []:
            if not isinstance(league, Mapping) or str(league.get("slug") or "").lower() != "mlb": continue
            out.extend(e for e in (league.get("events") or []) if isinstance(e, Mapping))
    return out


def fetch_espn_draftkings_game_quotes(
    *, slate_date: date, schedule: Iterable[GameSnapshot], retrieved_at: datetime,
    opener: Callable = urlopen, ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> EspnGameOddsSnapshot:
    retrieved = _aware_utc(retrieved_at)
    if not isinstance(slate_date, date):
        raise EspnGameOddsError("ESPN_SLATE_DATE_REQUIRED")
    params = {
        "sport": "baseball", "league": "mlb", "region": "us", "lang": "en",
        "contentorigin": "espn", "dates": slate_date.strftime("%Y%m%d"),
    }
    url = f"{BASE}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Referer": "https://www.espn.com/"})
    try:
        with opener(req, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise EspnGameOddsError(f"ESPN_GAME_ODDS_FETCH_FAILED:{type(exc).__name__}") from exc
    if not isinstance(payload, Mapping):
        raise EspnGameOddsError("ESPN_GAME_ODDS_RESPONSE_INVALID")
    games = list(schedule); quotes: list[dict[str, Any]] = []; failures: list[dict[str, Any]] = []
    events = _extract_mlb_events(payload)
    if not events:
        raise EspnGameOddsError("ESPN_GAME_ODDS_NO_MLB_EVENTS")
    for event in events:
        try:
            game = bind_espn_event(event, games)
            snap = parse_espn_event_odds(event, game=game, retrieved_at=retrieved, ttl_seconds=ttl_seconds)
            quotes.extend(snap.quotes); failures.extend(snap.failures)
        except Exception as exc:
            failures.append({"provider_event_id": str(event.get("id") or ""), "reason": str(exc)})
    return EspnGameOddsSnapshot(tuple(quotes), tuple(failures))
