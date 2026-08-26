"""Canonical CFB acquisition/normalization for schedule, advanced team metrics and odds.

Network transport is injectable. Team binding is exact against CFBD-published school,
abbreviation, mascot-qualified school and alternate names; unknown provider names fail
closed rather than being guessed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CFBD_BASE = "https://api.collegefootballdata.com"
ODDS_BASE = "https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds"
CFB_SOURCE_CONTRACT = "CFB_AUTO_SOURCE_V1"
SUPPORTED_GAME_MARKETS = frozenset({"MONEYLINE", "SPREAD", "TOTAL"})


class CFBSourceError(ValueError):
    pass


@dataclass(frozen=True)
class CFBGame:
    game_id: str
    season: int
    week: int
    start_ts: str
    home_team: str
    away_team: str
    neutral_site: bool
    venue: str | None = None
    weather: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class CFBTeamMetrics:
    team: str
    season: int
    through_week: int
    sample_source: str
    off_ppa_rush: float
    off_ppa_dropback: float
    def_ppa_rush_allowed: float
    def_ppa_dropback_allowed: float
    off_success_rate: float
    def_success_rate_allowed: float
    standard_down_ppa: float
    passing_down_success_rate: float
    eckel_rate: float
    points_per_eckel: float
    points_per_drive: float
    net_field_position: float
    explosive_rate: float
    feature_asof_ts: str
    source_contract: str = CFB_SOURCE_CONTRACT

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CFBQuote:
    game_id: str
    period: str
    market: str
    entity_id: str
    side: str
    line: float
    american_odds: float
    book_key: str
    sportsbook: str
    retrieved_at: str
    offer_id: str
    is_alternate: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dt(value: Any, name: str) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            raise CFBSourceError(f"{name} required")
        try:
            out = datetime.fromisoformat(text)
        except ValueError as exc:
            raise CFBSourceError(f"{name} invalid") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CFBSourceError(f"{name} timezone required")
    return out.astimezone(timezone.utc)


def _num(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBSourceError(f"{name} numeric required") from exc
    if not isfinite(out):
        raise CFBSourceError(f"{name} finite required")
    return out


def _norm_name(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _json_get(url: str, *, headers: Mapping[str, str] | None, opener: Callable = urlopen) -> Any:
    req = Request(url, headers=dict(headers or {}))
    try:
        with opener(req, timeout=20) as response:
            raw = response.read()
    except Exception as exc:
        raise CFBSourceError(f"SOURCE_FETCH_FAILED:{type(exc).__name__}:{exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise CFBSourceError("SOURCE_JSON_INVALID") from exc


def _cfbd_url(path: str, params: Mapping[str, Any] | None = None) -> str:
    query = urlencode({k: v for k, v in (params or {}).items() if v is not None})
    return f"{CFBD_BASE}{path}" + (f"?{query}" if query else "")


def _auth(token: str) -> dict[str, str]:
    key = str(token or "").strip()
    if not key:
        raise CFBSourceError("CFBD_API_KEY_REQUIRED")
    return {"Authorization": f"Bearer {key}"}


def fetch_cfbd_teams(*, season: int, cfbd_api_key: str, opener: Callable = urlopen) -> list[dict[str, Any]]:
    data = _json_get(_cfbd_url("/teams/fbs", {"year": int(season)}), headers=_auth(cfbd_api_key), opener=opener)
    if not isinstance(data, list):
        raise CFBSourceError("CFBD_TEAMS_NOT_LIST")
    return [dict(x) for x in data if isinstance(x, Mapping)]


def build_team_alias_index(team_rows: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    index: dict[str, str] = {}
    collisions: set[str] = set()
    for row in team_rows:
        school = str(row.get("school") or "").strip()
        if not school:
            continue
        aliases: list[str] = [school]
        abbr = str(row.get("abbreviation") or "").strip()
        mascot = str(row.get("mascot") or "").strip()
        if abbr:
            aliases.append(abbr)
        if mascot:
            aliases.append(f"{school} {mascot}")
        raw_alt = row.get("alternateNames")
        if isinstance(raw_alt, list):
            aliases.extend(str(x).strip() for x in raw_alt if str(x).strip())
        for alias in aliases:
            key = _norm_name(alias)
            if not key:
                continue
            prior = index.get(key)
            if prior is None:
                index[key] = school
            elif prior != school:
                collisions.add(key)
    for key in collisions:
        index.pop(key, None)
    return index


def bind_provider_team(name: str, alias_index: Mapping[str, str]) -> str:
    key = _norm_name(name)
    if not key or key not in alias_index:
        raise CFBSourceError(f"CFB_PROVIDER_TEAM_UNRESOLVED:{name}")
    return str(alias_index[key])


def fetch_cfbd_games(*, season: int, week: int, cfbd_api_key: str, opener: Callable = urlopen) -> list[CFBGame]:
    data = _json_get(
        _cfbd_url("/games", {"year": int(season), "week": int(week), "seasonType": "regular", "classification": "fbs"}),
        headers=_auth(cfbd_api_key), opener=opener,
    )
    if not isinstance(data, list):
        raise CFBSourceError("CFBD_GAMES_NOT_LIST")
    out: list[CFBGame] = []
    for row in data:
        if not isinstance(row, Mapping):
            continue
        start = _dt(row.get("startDate"), "startDate")
        home = str(row.get("homeTeam") or "").strip()
        away = str(row.get("awayTeam") or "").strip()
        if not home or not away:
            raise CFBSourceError("CFBD_GAME_TEAM_MISSING")
        out.append(CFBGame(
            game_id=str(row.get("id")), season=int(row.get("season", season)), week=int(row.get("week", week)),
            start_ts=start.isoformat(), home_team=home, away_team=away,
            neutral_site=bool(row.get("neutralSite", False)), venue=str(row.get("venue") or "").strip() or None,
        ))
    return out


def _nested(row: Mapping[str, Any], *path: str) -> Any:
    cur: Any = row
    for key in path:
        if not isinstance(cur, Mapping) or key not in cur:
            raise CFBSourceError("CFBD_ADVANCED_FIELD_MISSING:" + ".".join(path))
        cur = cur[key]
    return cur


def _points_by_team(completed_games: Iterable[Mapping[str, Any]], *, through_week: int) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in completed_games:
        if not isinstance(row, Mapping):
            continue
        try:
            wk = int(row.get("week", 0))
        except Exception:
            continue
        if wk > through_week or row.get("completed") is not True:
            continue
        home, away = str(row.get("homeTeam") or "").strip(), str(row.get("awayTeam") or "").strip()
        hp, ap = row.get("homePoints"), row.get("awayPoints")
        if home and hp is not None:
            out[home] = out.get(home, 0.0) + _num(hp, "homePoints")
        if away and ap is not None:
            out[away] = out.get(away, 0.0) + _num(ap, "awayPoints")
    return out


def normalize_advanced_team_metrics(
    row: Mapping[str, Any], *, through_week: int, feature_asof_ts: datetime | str,
    season_points: Mapping[str, float], sample_source: str,
) -> CFBTeamMetrics:
    team = str(row.get("team") or "").strip()
    if not team:
        raise CFBSourceError("CFBD_ADVANCED_TEAM_MISSING")
    off = _nested(row, "offense")
    deff = _nested(row, "defense")
    if not isinstance(off, Mapping) or not isinstance(deff, Mapping):
        raise CFBSourceError("CFBD_ADVANCED_OFFENSE_DEFENSE_INVALID")
    drives = _num(off.get("drives"), "offense.drives")
    if drives <= 0:
        raise CFBSourceError("CFBD_ADVANCED_DRIVES_ZERO")
    opps = _num(off.get("totalOpportunies"), "offense.totalOpportunies")
    off_fp = _num(_nested(off, "fieldPosition", "averageStart"), "offense.fieldPosition.averageStart")
    def_fp = _num(_nested(deff, "fieldPosition", "averageStart"), "defense.fieldPosition.averageStart")
    asof = _dt(feature_asof_ts, "feature_asof_ts")
    return CFBTeamMetrics(
        team=team, season=int(row.get("season")), through_week=int(through_week), sample_source=sample_source,
        off_ppa_rush=_num(_nested(off, "rushingPlays", "ppa"), "offense.rushingPlays.ppa"),
        off_ppa_dropback=_num(_nested(off, "passingPlays", "ppa"), "offense.passingPlays.ppa"),
        def_ppa_rush_allowed=_num(_nested(deff, "rushingPlays", "ppa"), "defense.rushingPlays.ppa"),
        def_ppa_dropback_allowed=_num(_nested(deff, "passingPlays", "ppa"), "defense.passingPlays.ppa"),
        off_success_rate=_num(off.get("successRate"), "offense.successRate"),
        def_success_rate_allowed=_num(deff.get("successRate"), "defense.successRate"),
        standard_down_ppa=_num(_nested(off, "standardDowns", "ppa"), "offense.standardDowns.ppa"),
        passing_down_success_rate=_num(_nested(off, "passingDowns", "successRate"), "offense.passingDowns.successRate"),
        eckel_rate=float(opps / drives),
        points_per_eckel=_num(off.get("pointsPerOpportunity"), "offense.pointsPerOpportunity"),
        points_per_drive=float(_num(season_points.get(team, 0.0), "season_points") / drives),
        net_field_position=float(off_fp - def_fp),
        explosive_rate=_num(off.get("explosiveness"), "offense.explosiveness"),
        feature_asof_ts=asof.isoformat(),
    )


def fetch_cfbd_team_metrics(
    *, season: int, week: int, cfbd_api_key: str, now: datetime,
    opener: Callable = urlopen,
) -> dict[str, CFBTeamMetrics]:
    current = _dt(now, "now")
    through_week = int(week) - 1
    metric_season = int(season)
    sample_source = "CURRENT_SEASON_PRIOR_WEEKS"
    params: dict[str, Any] = {"year": metric_season, "excludeGarbageTime": "true", "classification": "fbs"}
    if through_week >= 1:
        params["endWeek"] = through_week
    else:
        metric_season -= 1
        params["year"] = metric_season
        through_week = 99
        sample_source = "PRIOR_SEASON_FALLBACK"
    advanced = _json_get(_cfbd_url("/stats/season/advanced", params), headers=_auth(cfbd_api_key), opener=opener)
    games = _json_get(_cfbd_url("/games", {"year": metric_season, "seasonType": "regular", "classification": "fbs"}), headers=_auth(cfbd_api_key), opener=opener)
    if not isinstance(advanced, list) or not isinstance(games, list):
        raise CFBSourceError("CFBD_ADVANCED_OR_GAMES_NOT_LIST")
    pts = _points_by_team(games, through_week=through_week)
    out: dict[str, CFBTeamMetrics] = {}
    for row in advanced:
        if not isinstance(row, Mapping):
            continue
        metric = normalize_advanced_team_metrics(row, through_week=through_week, feature_asof_ts=current, season_points=pts, sample_source=sample_source)
        out[metric.team] = metric
    if not out:
        raise CFBSourceError("CFBD_ADVANCED_EMPTY")
    return out


def _offer_id(event_id: str, book_key: str, market: str, side: str, line: float, retrieved_at: str) -> str:
    raw = "|".join((event_id, book_key, market, side, repr(float(line)), retrieved_at)).encode()
    return sha256(raw).hexdigest()


def parse_the_odds_api_quotes(
    payload: Any, *, games: Iterable[CFBGame], alias_index: Mapping[str, str],
    bookmakers: Iterable[str] = ("draftkings",),
) -> list[CFBQuote]:
    if not isinstance(payload, list):
        raise CFBSourceError("ODDS_PAYLOAD_NOT_LIST")
    by_matchup = {(g.home_team, g.away_team): g for g in games}
    allowed_books = {str(x).strip().lower() for x in bookmakers if str(x).strip()}
    out: list[CFBQuote] = []
    for event in payload:
        if not isinstance(event, Mapping):
            continue
        home = bind_provider_team(str(event.get("home_team") or ""), alias_index)
        away = bind_provider_team(str(event.get("away_team") or ""), alias_index)
        game = by_matchup.get((home, away))
        if game is None:
            raise CFBSourceError(f"CFB_ODDS_GAME_UNRESOLVED:{away}@{home}")
        event_id = str(event.get("id") or "").strip()
        for book in event.get("bookmakers") or []:
            if not isinstance(book, Mapping):
                continue
            book_key = str(book.get("key") or "").strip().lower()
            if allowed_books and book_key not in allowed_books:
                continue
            sportsbook = str(book.get("title") or book_key).strip()
            book_ts = _dt(book.get("last_update"), "book.last_update")
            for market_row in book.get("markets") or []:
                if not isinstance(market_row, Mapping):
                    continue
                key = str(market_row.get("key") or "").strip().lower()
                canonical = {"h2h": "MONEYLINE", "spreads": "SPREAD", "totals": "TOTAL"}.get(key)
                if canonical is None:
                    continue
                retrieved = _dt(market_row.get("last_update") or book_ts, "market.last_update").isoformat()
                outcomes = [x for x in (market_row.get("outcomes") or []) if isinstance(x, Mapping)]
                home_spread: float | None = None
                if canonical == "SPREAD":
                    for outcome in outcomes:
                        try:
                            bound = bind_provider_team(str(outcome.get("name") or ""), alias_index)
                        except CFBSourceError:
                            continue
                        if bound == home:
                            home_spread = _num(outcome.get("point"), "spread.point")
                            break
                    if home_spread is None:
                        raise CFBSourceError("CFB_HOME_SPREAD_MISSING")
                for outcome in outcomes:
                    name = str(outcome.get("name") or "").strip()
                    price = _num(outcome.get("price"), "odds.price")
                    if canonical == "MONEYLINE":
                        team = bind_provider_team(name, alias_index)
                        side = "HOME" if team == home else "AWAY" if team == away else ""
                        line, entity = 0.0, game.game_id
                    elif canonical == "SPREAD":
                        team = bind_provider_team(name, alias_index)
                        side = "HOME" if team == home else "AWAY" if team == away else ""
                        line, entity = float(home_spread), game.game_id
                    else:
                        upper = name.upper()
                        if upper not in {"OVER", "UNDER"}:
                            raise CFBSourceError(f"CFB_TOTAL_SIDE_INVALID:{name}")
                        side = upper
                        line, entity = _num(outcome.get("point"), "total.point"), game.game_id
                    if not side:
                        raise CFBSourceError(f"CFB_ODDS_SIDE_UNRESOLVED:{name}")
                    out.append(CFBQuote(
                        game_id=game.game_id, period="FG", market=canonical, entity_id=entity,
                        side=side, line=float(line), american_odds=price, book_key=book_key,
                        sportsbook=sportsbook, retrieved_at=retrieved,
                        offer_id=_offer_id(event_id, book_key, canonical, side, float(line), retrieved),
                    ))
    return out


def fetch_the_odds_api_quotes(
    *, api_key: str, games: Iterable[CFBGame], alias_index: Mapping[str, str],
    bookmakers: Iterable[str] = ("draftkings",), opener: Callable = urlopen,
) -> list[CFBQuote]:
    key = str(api_key or "").strip()
    if not key:
        raise CFBSourceError("ODDS_API_KEY_REQUIRED")
    params = {
        "regions": "us", "markets": "h2h,spreads,totals", "oddsFormat": "american",
        "apiKey": key,
    }
    books = ",".join(str(x).strip() for x in bookmakers if str(x).strip())
    if books:
        params["bookmakers"] = books
    payload = _json_get(f"{ODDS_BASE}?{urlencode(params)}", headers=None, opener=opener)
    return parse_the_odds_api_quotes(payload, games=list(games), alias_index=alias_index, bookmakers=bookmakers)


def fetch_cfbd_weather(*, season: int, week: int, cfbd_api_key: str, opener: Callable = urlopen) -> dict[str, dict[str, Any]]:
    data = _json_get(
        _cfbd_url("/games/weather", {"year": int(season), "week": int(week), "seasonType": "regular", "classification": "fbs"}),
        headers=_auth(cfbd_api_key), opener=opener,
    )
    if not isinstance(data, list):
        raise CFBSourceError("CFBD_WEATHER_NOT_LIST")
    out: dict[str, dict[str, Any]] = {}
    for row in data:
        if not isinstance(row, Mapping):
            continue
        gid = str(row.get("id") or "").strip()
        if not gid:
            continue
        indoors = row.get("gameIndoors")
        if type(indoors) is not bool:
            raise CFBSourceError("CFBD_WEATHER_INDOOR_FLAG_MISSING")
        weather: dict[str, Any] = {"game_indoor": indoors, "source": "CFBD_GAMES_WEATHER"}
        if not indoors:
            weather["wind_speed"] = _num(row.get("windSpeed"), "weather.windSpeed")
            weather["temperature"] = _num(row.get("temperature"), "weather.temperature")
            weather["precipitation"] = None if row.get("precipitation") is None else _num(row.get("precipitation"), "weather.precipitation")
        out[gid] = weather
    return out


def attach_weather(games: Iterable[CFBGame], weather_by_game: Mapping[str, Mapping[str, Any]]) -> list[CFBGame]:
    out: list[CFBGame] = []
    for game in games:
        weather = weather_by_game.get(game.game_id)
        if not isinstance(weather, Mapping):
            raise CFBSourceError(f"CFB_WEATHER_MISSING:{game.game_id}")
        out.append(CFBGame(
            game_id=game.game_id, season=game.season, week=game.week, start_ts=game.start_ts,
            home_team=game.home_team, away_team=game.away_team, neutral_site=game.neutral_site,
            venue=game.venue, weather=dict(weather),
        ))
    return out
