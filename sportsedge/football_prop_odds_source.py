"""Event-level two-way football player-prop acquisition with key failover."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Callable, Iterable, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sportsedge.football_prop_run_machine import PROVIDER_MARKET_TO_STAT
from sportsedge.odds_keyring import fetch_with_key_failover

_BASE = "https://api.the-odds-api.com/v4"
_SPORT_KEYS = {"NFL": "americanfootball_nfl", "CFB": "americanfootball_ncaaf"}


class FootballPropOddsError(ValueError):
    pass


def _sport_key(sport: str) -> str:
    key = str(sport or "").strip().upper()
    if key not in _SPORT_KEYS:
        raise FootballPropOddsError(f"FOOTBALL_PROP_ODDS_SPORT_UNSUPPORTED:{key}")
    return _SPORT_KEYS[key]


def build_event_prop_odds_url(
    *, sport: str, event_id: str, bookmakers: Iterable[str] = ("draftkings",),
    markets: Iterable[str] | None = None,
) -> str:
    event = str(event_id or "").strip()
    if not event or "/" in event:
        raise FootballPropOddsError("FOOTBALL_PROP_ODDS_EVENT_ID_INVALID")
    requested = tuple(markets or PROVIDER_MARKET_TO_STAT.keys())
    unknown = sorted(set(requested).difference(PROVIDER_MARKET_TO_STAT))
    if unknown:
        raise FootballPropOddsError("FOOTBALL_PROP_ODDS_MARKET_UNSUPPORTED:" + ",".join(unknown))
    books = tuple(str(x).strip().lower() for x in bookmakers if str(x).strip())
    if not books:
        raise FootballPropOddsError("FOOTBALL_PROP_ODDS_BOOKMAKER_REQUIRED")
    params = {
        "regions": "us",
        "bookmakers": ",".join(books),
        "markets": ",".join(requested),
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    return f"{_BASE}/sports/{_sport_key(sport)}/events/{event}/odds?{urlencode(params)}"


def _http_fetch(url_without_key: str, key: str) -> Any:
    sep = "&" if "?" in url_without_key else "?"
    url = f"{url_without_key}{sep}{urlencode({'apiKey': key})}"
    with urlopen(
        Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge-Football-Props/1"}),
        timeout=20,
    ) as response:
        raw = response.read()
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FootballPropOddsError("FOOTBALL_PROP_ODDS_RESPONSE_JSON_INVALID") from exc


def fetch_event_prop_odds(
    api_keys: Sequence[str], *, sport: str, event_id: str,
    bookmakers: Iterable[str] = ("draftkings",),
    markets: Iterable[str] | None = None,
    fetcher: Callable[[str, str], Any] = _http_fetch,
):
    base = build_event_prop_odds_url(
        sport=sport, event_id=event_id, bookmakers=bookmakers, markets=markets,
    )
    result = fetch_with_key_failover(list(api_keys), lambda key: fetcher(base, key))
    if not isinstance(result.value, dict):
        raise FootballPropOddsError("FOOTBALL_PROP_ODDS_EVENT_RESPONSE_NOT_OBJECT")
    return result


def build_odds_snapshot(events: Sequence[dict[str, Any]], *, observed_at: datetime | None = None) -> dict[str, Any]:
    if not events or any(not isinstance(event, dict) for event in events):
        raise FootballPropOddsError("FOOTBALL_PROP_ODDS_EVENTS_REQUIRED")
    stamp = observed_at or datetime.now(timezone.utc)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise FootballPropOddsError("FOOTBALL_PROP_ODDS_OBSERVED_AT_TIMEZONE_REQUIRED")
    return {
        "schema_version": "FOOTBALL_PROP_ODDS_SNAPSHOT_V1",
        "observed_at": stamp.astimezone(timezone.utc).isoformat(),
        "events": [dict(event) for event in events],
    }
