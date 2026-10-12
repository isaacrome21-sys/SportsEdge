"""Historical GAME OUTCOMES from free public sources only. Research only.

Sources:
  - NFL / CFB: ESPN public scoreboard API
      https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
      https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard
    Historical days are fetched with ?dates=YYYYMMDD.
  - MLB: MLB StatsAPI schedule
      https://statsapi.mlb.com/api/v1/schedule?sportId=1&startDate=..&endDate=..

Responses are cached as JSON under a caller-supplied data dir so backtests
are reproducible without re-hitting the network. Unit tests must inject a
``getter`` returning recorded fixtures and never touch the network.

Only FINAL games yield outcomes. Non-final games are skipped (they carry no
verified outcome); a completed game with missing or malformed scores fails
closed.

No odds, no market prices, no betting authority.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ESPN_SCOREBOARD = {
    "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
    "cfb": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
}
MLB_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"


class OutcomeError(ValueError):
    pass


def _public_json(url):
    try:
        request = Request(url, headers={"User-Agent": "SportsEdge-free-research/1.0",
                                        "Accept": "application/json"})
        with urlopen(request, timeout=20) as response:
            if response.status != 200:
                return None
            data = json.loads(response.read(8_000_000))
            return data if isinstance(data, dict) else None
    except (OSError, ValueError, TimeoutError, json.JSONDecodeError):
        return None


def _cached_fetch(url, *, getter, cache_dir):
    """Fetch JSON with optional on-disk cache. getter(url) may be injected."""
    cache_path = None
    if cache_dir is not None:
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        cache_path = Path(cache_dir) / (key + ".json")
        if cache_path.exists():
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise OutcomeError("BACKTEST_CACHE_CORRUPT:" + key) from exc
    data = (getter or _public_json)(url)
    if not isinstance(data, dict):
        raise OutcomeError("BACKTEST_SOURCE_UNAVAILABLE")
    if cache_path is not None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(data), encoding="utf-8")
        except OSError as exc:
            raise OutcomeError("BACKTEST_CACHE_WRITE_FAILED") from exc
    return data


def _clock(value, name):
    try:
        d = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise OutcomeError(name + "_UNVERIFIED") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise OutcomeError(name + "_TIMEZONE_REQUIRED")
    return d.astimezone(timezone.utc)


def _int_score(value, name):
    try:
        score = int(str(value).strip())
    except (ValueError, TypeError, AttributeError) as exc:
        raise OutcomeError(name + "_UNVERIFIED") from exc
    if score < 0:
        raise OutcomeError(name + "_NEGATIVE")
    return score


def fetch_football_scoreboard(sport, *, dates=None, season=None, week=None,
                              getter=None, cache_dir=None):
    """Fetch one ESPN scoreboard page. ``dates`` is YYYYMMDD (preferred for
    historical days); ``season``/``week`` select a schedule week instead."""
    sport = str(sport or "").lower().strip()
    if sport not in ESPN_SCOREBOARD:
        raise OutcomeError("BACKTEST_SPORT_UNSUPPORTED:" + sport)
    params = {}
    if dates is not None:
        d = str(dates).strip()
        if len(d) != 8 or not d.isdigit():
            raise OutcomeError("BACKTEST_DATES_INVALID")
        params["dates"] = d
    if season is not None:
        params["season"] = str(int(season))
    if week is not None:
        params["week"] = str(int(week))
    url = ESPN_SCOREBOARD[sport]
    if params:
        url += "?" + urlencode(params)
    data = _cached_fetch(url, getter=getter, cache_dir=cache_dir)
    events = data.get("events")
    if not isinstance(events, list):
        raise OutcomeError("BACKTEST_SCOREBOARD_EVENTS_NOT_LIST")
    return events


def parse_completed_football_games(events):
    """Parse ESPN scoreboard events -> completed games with verified scores.

    Returns [{event_id, kickoff, home_team, away_team, home_score,
    away_score}]. Non-completed events are skipped; completed events with
    missing/malformed scores fail closed.
    """
    games = []
    for event in events:
        if not isinstance(event, dict):
            continue
        status = event.get("status") or {}
        stype = status.get("type") or {}
        if stype.get("completed") is not True:
            continue  # no verified outcome yet
        event_id = str(event.get("id") or "").strip()
        kickoff = str(event.get("date") or "").strip()
        if not event_id or not kickoff:
            raise OutcomeError("BACKTEST_EVENT_IDENTITY_UNVERIFIED")
        _clock(kickoff, "BACKTEST_KICKOFF")
        competitions = event.get("competitions") or []
        if not competitions or not isinstance(competitions[0], dict):
            raise OutcomeError("BACKTEST_COMPETITION_MISSING:" + event_id)
        competitors = competitions[0].get("competitors") or []
        home = next((c for c in competitors
                     if isinstance(c, dict) and c.get("homeAway") == "home"), None)
        away = next((c for c in competitors
                     if isinstance(c, dict) and c.get("homeAway") == "away"), None)
        if home is None or away is None:
            raise OutcomeError("BACKTEST_COMPETITORS_UNVERIFIED:" + event_id)
        games.append({
            "event_id": event_id,
            "kickoff": kickoff,
            "home_team": str((home.get("team") or {}).get("displayName") or "").strip(),
            "away_team": str((away.get("team") or {}).get("displayName") or "").strip(),
            "home_score": _int_score(home.get("score"), "BACKTEST_HOME_SCORE"),
            "away_score": _int_score(away.get("score"), "BACKTEST_AWAY_SCORE"),
        })
    return games


def fetch_mlb_schedule(start_date, end_date, *, getter=None, cache_dir=None):
    """Fetch MLB StatsAPI schedule for a date range (YYYY-MM-DD).

    Returns the raw ``dates`` list; parse with parse_completed_mlb_games.
    """
    for name, value in (("start_date", start_date), ("end_date", end_date)):
        v = str(value or "").strip()
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError as exc:
            raise OutcomeError("BACKTEST_MLB_DATE_INVALID:" + name) from exc
    url = MLB_SCHEDULE + "?" + urlencode({
        "sportId": 1, "startDate": str(start_date).strip(),
        "endDate": str(end_date).strip(), "hydrate": "linescore",
    })
    data = _cached_fetch(url, getter=getter, cache_dir=cache_dir)
    dates = data.get("dates")
    if not isinstance(dates, list):
        raise OutcomeError("BACKTEST_MLB_DATES_NOT_LIST")
    return dates


def parse_completed_mlb_games(dates):
    """Parse StatsAPI schedule ``dates`` -> completed games with scores."""
    games = []
    for day in dates:
        if not isinstance(day, dict):
            continue
        for game in day.get("games") or []:
            if not isinstance(game, dict):
                continue
            status = str(((game.get("status") or {}).get("detailedState") or ""))
            if status != "Final":
                continue  # no verified outcome yet
            teams = game.get("teams") or {}
            home = teams.get("home") or {}
            away = teams.get("away") or {}
            game_pk = game.get("gamePk")
            game_date = str(game.get("gameDate") or "").strip()
            if game_pk is None or not game_date:
                raise OutcomeError("BACKTEST_MLB_GAME_IDENTITY_UNVERIFIED")
            _clock(game_date, "BACKTEST_KICKOFF")
            games.append({
                "event_id": str(game_pk),
                "kickoff": game_date,
                "home_team": str(((home.get("team") or {}).get("name")) or "").strip(),
                "away_team": str(((away.get("team") or {}).get("name")) or "").strip(),
                "home_score": _int_score(home.get("score"), "BACKTEST_HOME_SCORE"),
                "away_score": _int_score(away.get("score"), "BACKTEST_AWAY_SCORE"),
            })
    return games


def settle_game(game, market, selection, line=None):
    """Settle one (market, selection) against a completed game.

    Returns 1.0 (win), 0.0 (loss), or 0.5 (push). Markets: ML/MONEYLINE,
    SPREAD, TOTAL. selection in {HOME, AWAY} for ML/SPREAD and
    {OVER, UNDER} for TOTAL. line required for SPREAD/TOTAL.
    """
    for key in ("home_score", "away_score"):
        if not isinstance(game.get(key), int):
            raise OutcomeError("BACKTEST_GAME_SCORES_UNVERIFIED")
    hs, aws = game["home_score"], game["away_score"]
    market = str(market or "").upper().strip()
    selection = str(selection or "").upper().strip()

    if market in ("ML", "MONEYLINE"):
        if selection == "HOME":
            return 1.0 if hs > aws else 0.0
        if selection == "AWAY":
            return 1.0 if aws > hs else 0.0
        raise OutcomeError("BACKTEST_SELECTION_INVALID:" + selection)
    if market == "SPREAD":
        if line is None:
            raise OutcomeError("BACKTEST_LINE_REQUIRED:SPREAD")
        try:
            ln = float(line)
        except (ValueError, TypeError) as exc:
            raise OutcomeError("BACKTEST_LINE_UNVERIFIED") from exc
        if selection == "HOME":
            margin = hs - aws + ln
        elif selection == "AWAY":
            margin = aws - hs + ln
        else:
            raise OutcomeError("BACKTEST_SELECTION_INVALID:" + selection)
        if margin > 0:
            return 1.0
        if margin < 0:
            return 0.0
        return 0.5
    if market == "TOTAL":
        if line is None:
            raise OutcomeError("BACKTEST_LINE_REQUIRED:TOTAL")
        try:
            ln = float(line)
        except (ValueError, TypeError) as exc:
            raise OutcomeError("BACKTEST_LINE_UNVERIFIED") from exc
        total = hs + aws
        if selection == "OVER":
            if total > ln:
                return 1.0
            if total < ln:
                return 0.0
            return 0.5
        if selection == "UNDER":
            if total < ln:
                return 1.0
            if total > ln:
                return 0.0
            return 0.5
        raise OutcomeError("BACKTEST_SELECTION_INVALID:" + selection)
    raise OutcomeError("BACKTEST_MARKET_UNSUPPORTED:" + market)
