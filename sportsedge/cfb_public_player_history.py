"""Independent public CFB player game-log history from free ESPN endpoints.

Mirrors the NFL collector. Resolves player by display name, fetches college
football gamelog, returns prior completed games. No odds, no trusted features.
Requires unique pregame fixture and at least 4 prior games (CFB samples are
smaller). Research only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import re
from .football_gamelog_decode import decode_football_event, FootballGamelogSchemaError

ESPN_SEARCH = "https://site.web.api.espn.com/apis/search/v2"
ESPN_GAMELOG = "https://site.web.api.espn.com/apis/common/v3/sports/football/college-football/athletes"
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"


class MissingCFBHistory(ValueError):
    pass


def _clock(value, name):
    try:
        d = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise MissingCFBHistory(name + "_UNVERIFIED") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise MissingCFBHistory(name + "_TIMEZONE_REQUIRED")
    return d.astimezone(timezone.utc)


def _norm(value):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


def public_json(url):
    try:
        request = Request(url, headers={"User-Agent": "SportsEdge-free-research/1.0",
                                        "Accept": "application/json"})
        with urlopen(request, timeout=12) as response:
            if response.status != 200:
                return None
            data = json.loads(response.read(4_000_000))
            return data if isinstance(data, dict) else None
    except (OSError, ValueError, TimeoutError, json.JSONDecodeError):
        return None


class CFBPlayerPublicSource:
    def __init__(self, *, getter=None):
        self.getter = getter or public_json
        self.cache = {}

    def _fetch(self, url):
        if url not in self.cache:
            try:
                data = self.getter(url)
                self.cache[url] = data if isinstance(data, dict) else None
            except (OSError, ValueError, TypeError, TimeoutError):
                self.cache[url] = None
        return self.cache[url]

    def _game(self, away, home, owner_kickoff, now):
        if owner_kickoff <= now:
            raise MissingCFBHistory("STARTED_GAME_REQUIRES_VERIFIED_LIVE_PROP_ENGINE")
        selected = []
        for date in {(owner_kickoff - timedelta(days=1)).date(), owner_kickoff.date()}:
            url = ESPN_SCOREBOARD + "?" + urlencode({"dates": date.strftime("%Y%m%d")})
            resp = self._fetch(url)
            if resp is None or not isinstance(resp.get("events"), list):
                continue
            for event in resp["events"]:
                comps = event.get("competitions") or []
                if not comps:
                    continue
                cs = comps[0].get("competitors") or []
                home_cs = next((c for c in cs if c.get("homeAway") == "home"), None)
                away_cs = next((c for c in cs if c.get("homeAway") == "away"), None)
                if not home_cs or not away_cs:
                    continue
                if (_norm((home_cs.get("team") or {}).get("displayName")) != _norm(home) or
                    _norm((away_cs.get("team") or {}).get("displayName")) != _norm(away)):
                    continue
                try:
                    start = _clock(event.get("date"), "CFB_SCHEDULE_START")
                except MissingCFBHistory:
                    continue
                if abs((start - owner_kickoff).total_seconds()) > 4 * 3600:
                    continue
                selected.append(event)
        unique = {str(e.get("id")): e for e in selected if e.get("id")}
        if len(unique) != 1:
            raise MissingCFBHistory("CFB_PUBLIC_FIXTURE_NOT_UNIQUELY_VERIFIED")
        return next(iter(unique.values()))

    def _resolve_athlete(self, player_name, allowed_team_ids):
        url = ESPN_SEARCH + "?" + urlencode({"query": player_name, "limit": "10", "type": "player"})
        data = self._fetch(url)
        items = ((data or {}).get("results") or [{}])[0].get("contents") or []
        matches = []
        for item in items:
            athlete = (item.get("player") or {})
            if _norm(athlete.get("displayName") or athlete.get("fullName")) != _norm(player_name):
                continue
            team = athlete.get("team") or {}
            tid = str(team.get("id") or "") if isinstance(team, dict) else ""
            # A global name match without independently verified current
            # team membership is NOT enough to originate a player wager.
            if tid in allowed_team_ids:
                matches.append(athlete)
        if len(matches) != 1:
            raise MissingCFBHistory("PLAYER_NOT_UNIQUELY_RESOLVED_FROM_ESPN_SEARCH")
        return matches[0]

    def prior_games(self, *, away, home, player_name, owner_kickoff,
                    as_of, max_games=10):
        now = _clock(as_of, "MODEL_AS_OF")
        proposed = _clock(owner_kickoff, "OWNER_GAME_START")
        game = self._game(away, home, proposed, now)
        kickoff = _clock(game.get("date"), "CFB_SCHEDULE_START")
        if kickoff <= now:
            raise MissingCFBHistory("STARTED_GAME_REQUIRES_VERIFIED_LIVE_PROP_ENGINE")

        competitors = ((game.get("competitions") or [{}])[0].get("competitors") or [])
        allowed_team_ids = {str((c.get("team") or {}).get("id") or "")
                            for c in competitors if isinstance(c, dict)}
        if len(allowed_team_ids) != 2 or "" in allowed_team_ids:
            raise MissingCFBHistory("ESPN_FIXTURE_TEAM_IDS_UNVERIFIED")
        athlete = self._resolve_athlete(player_name, allowed_team_ids)
        athlete_id = str(athlete.get("id") or "")
        if not athlete_id:
            raise MissingCFBHistory("ATHLETE_ID_MISSING")

        url = f"{ESPN_GAMELOG}/{athlete_id}/gamelog"
        data = self._fetch(url)
        if not isinstance(data, dict):
            raise MissingCFBHistory("CFB_GAMELOG_UNAVAILABLE")

        events = data.get("events") or []
        if not isinstance(events, list):
            raise MissingCFBHistory("ESPN_GAMELOG_EVENTS_NOT_LIST")
        hist = []
        invalid_schema = 0
        for event in events:
            try:
                event_date = _clock(event.get("date"), "GAMELOG_DATE")
                if event_date >= now or event_date >= kickoff:
                    continue
                event_id = str(event.get("id") or "").strip()
                if not event_id:
                    raise MissingCFBHistory("PRIOR_GAME_ID_UNVERIFIED")
                actual = decode_football_event(data, event)
                hist.append((event_date, event_id, actual))
            except (FootballGamelogSchemaError, ValueError, TypeError,
                    KeyError, MissingCFBHistory):
                invalid_schema += 1
                continue

        hist.sort(key=lambda x: x[0], reverse=True)
        latest = []
        seen = set()
        for prior in hist:
            if prior[1] in seen:
                continue
            seen.add(prior[1])
            latest.append(prior)
            if len(latest) >= max_games:
                break
        if len(latest) < 5:
            raise MissingCFBHistory("FEWER_THAN_FIVE_VERIFIED_NAMED_PRIOR_GAMES")

        dates = [d.isoformat() for d, _, _ in latest]
        return {
            "game_id": str(game.get("id") or ""),
            "player_id": athlete_id,
            "player_name": athlete.get("displayName") or player_name,
            "home_team": home, "away_team": away,
            "kickoff_utc": kickoff.isoformat(), "source_as_of_utc": now.isoformat(),
            "prior_game_times_utc": dates,
            "features": {"game_history": [stats for _, _, stats in latest]},
            "explicit_stat_fields": sorted(set().union(*(set(x[2]) for x in latest))),
            "schema_rejected_prior_events": invalid_schema,
            "source_endpoint": url,
            "prior_game_count": len(latest),
        }
