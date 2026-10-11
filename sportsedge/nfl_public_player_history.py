"""Independent public NFL player game-log history from free ESPN endpoints.

Resolves player by display name via ESPN search, fetches gamelog, and extracts
prior completed games with normalized traditional box-score stats
(passing_yards, passing_tds, pass_attempts, completions, interceptions,
rushing_yards, rush_attempts, receiving_yards, receptions). No odds, no Next
Gen tracking, no trusted caller features. Requires unique pregame fixture and
at least 5 prior games. Research only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
import json
import re

ESPN_SEARCH = "https://site.web.api.espn.com/apis/search/v2"
ESPN_GAMELOG = "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes"
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"

# ESPN gamelog `names` -> normalized box-score field consumed by the pricer.
_ESPN_STAT_TO_FIELD = {
    "passingYards": "passing_yards",
    "passingTouchdowns": "passing_tds",
    "passingAttempts": "pass_attempts",
    "completions": "completions",
    "interceptions": "interceptions",
    "rushingYards": "rushing_yards",
    "rushingAttempts": "rush_attempts",
    "receivingYards": "receiving_yards",
    "receptions": "receptions",
}


class MissingNFLHistory(ValueError):
    pass


def _clock(value, name):
    try:
        d = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise MissingNFLHistory(name + "_UNVERIFIED") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise MissingNFLHistory(name + "_TIMEZONE_REQUIRED")
    return d.astimezone(timezone.utc)


def _norm(value):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


def _stat_number(value):
    """Parse an ESPN stat cell; return None when absent or non-numeric."""
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _normalize_player_stats(named):
    """Extract normalized fields from an ESPN name->value stat mapping.

    Only fields present with numeric values are emitted. Missing fields are
    omitted so the empirical pricer fails closed instead of imputing.
    """
    out = {}
    for espn_name, field in _ESPN_STAT_TO_FIELD.items():
        if espn_name in named:
            v = _stat_number(named.get(espn_name))
            if v is not None:
                out[field] = v
    return out


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


class NFLPlayerPublicSource:
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
            raise MissingNFLHistory("STARTED_GAME_REQUIRES_VERIFIED_LIVE_PROP_ENGINE")
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
                    start = _clock(event.get("date"), "NFL_SCHEDULE_START")
                except MissingNFLHistory:
                    continue
                if abs((start - owner_kickoff).total_seconds()) > 3 * 3600:
                    continue
                selected.append(event)
        unique = {str(e.get("id")): e for e in selected if e.get("id")}
        if len(unique) != 1:
            raise MissingNFLHistory("NFL_PUBLIC_FIXTURE_NOT_UNIQUELY_VERIFIED")
        return next(iter(unique.values()))

    def _resolve_athlete(self, player_name):
        url = ESPN_SEARCH + "?" + urlencode({"query": player_name, "limit": "5", "type": "player"})
        data = self._fetch(url)
        items = ((data or {}).get("results") or [{}])[0].get("contents") or []
        matches = []
        for item in items:
            if not isinstance(item, dict):
                continue
            # Real ESPN contents carry displayName/uid directly; tolerate a
            # nested "player" wrapper if a future shape introduces one.
            node = item.get("player") if isinstance(item.get("player"), dict) else item
            if _norm(node.get("displayName") or node.get("fullName")) != _norm(player_name):
                continue
            athlete_id = ""
            uid = str(node.get("uid") or "")
            m = re.search(r"a:(\d+)", uid)
            if m:
                athlete_id = m.group(1)
            elif str(node.get("id") or "").isdigit():
                athlete_id = str(node.get("id"))
            if not athlete_id:
                continue
            matches.append({"id": athlete_id,
                            "displayName": node.get("displayName") or player_name})
        if len(matches) != 1:
            raise MissingNFLHistory("PLAYER_NOT_UNIQUELY_RESOLVED_FROM_ESPN_SEARCH")
        return matches[0]

    def prior_games(self, *, away, home, player_name, owner_kickoff,
                    as_of, max_games=12):
        """Return actual prior game box-score stats for a named NFL player."""
        now = _clock(as_of, "MODEL_AS_OF")
        proposed = _clock(owner_kickoff, "OWNER_GAME_START")
        game = self._game(away, home, proposed, now)
        kickoff = _clock(game.get("date"), "NFL_SCHEDULE_START")
        if kickoff <= now:
            raise MissingNFLHistory("STARTED_GAME_REQUIRES_VERIFIED_LIVE_PROP_ENGINE")

        athlete = self._resolve_athlete(player_name)
        athlete_id = str(athlete.get("id") or "")
        if not athlete_id:
            raise MissingNFLHistory("ATHLETE_ID_MISSING")

        url = f"{ESPN_GAMELOG}/{athlete_id}/gamelog"
        data = self._fetch(url)
        if not isinstance(data, dict):
            raise MissingNFLHistory("NFL_GAMELOG_UNAVAILABLE")

        # ESPN gamelog shape: top-level `names` aligns with each event's stat
        # array; per-event metadata lives in `events` (dict keyed by eventId);
        # stat arrays live under seasonTypes -> categories -> events.
        names = data.get("names") or []
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise MissingNFLHistory("NFL_GAMELOG_STAT_NAMES_MISSING")
        events_meta = data.get("events") or {}
        if not isinstance(events_meta, dict):
            raise MissingNFLHistory("NFL_GAMELOG_EVENTS_MALFORMED")
        stat_arrays = {}
        for season in data.get("seasonTypes") or []:
            if not isinstance(season, dict):
                continue
            for category in season.get("categories") or []:
                if not isinstance(category, dict):
                    continue
                for ev in category.get("events") or []:
                    if not isinstance(ev, dict):
                        continue
                    eid = str(ev.get("eventId") or "")
                    stats = ev.get("stats")
                    if eid and isinstance(stats, list) and eid not in stat_arrays:
                        stat_arrays[eid] = stats

        hist = []
        for eid, meta in events_meta.items():
            if not isinstance(meta, dict):
                continue
            stats = stat_arrays.get(str(eid)) or stat_arrays.get(str(meta.get("id") or ""))
            if not isinstance(stats, list) or len(stats) != len(names):
                # Names and stat array misaligned or absent: skip the game
                # rather than invent values (fail-closed).
                continue
            try:
                event_date = _clock(meta.get("gameDate"), "GAMELOG_DATE")
            except (ValueError, TypeError, MissingNFLHistory):
                continue
            if event_date >= now or event_date >= kickoff:
                continue
            named = {name: value for name, value in zip(names, stats)}
            normalized = _normalize_player_stats(named)
            opponent = meta.get("opponent")
            hist.append((event_date, str(eid), {
                "opponent": (opponent.get("abbreviation")
                             if isinstance(opponent, dict) else None),
                "result": meta.get("gameResult"),
                **normalized,
            }))

        hist.sort(key=lambda x: x[0], reverse=True)
        latest = hist[:max_games]
        if len(latest) < 5:
            raise MissingNFLHistory("FEWER_THAN_FIVE_VERIFIED_PRIOR_GAMES")

        dates = [d.isoformat() for d, _, _ in latest]
        return {
            "game_id": str(game.get("id") or ""),
            "player_id": athlete_id,
            "player_name": athlete.get("displayName") or player_name,
            "home_team": home,
            "away_team": away,
            "kickoff_utc": kickoff.isoformat(),
            "source_as_of_utc": now.isoformat(),
            "prior_game_times_utc": dates,
            "features": {"game_history": [stats for _, _, stats in latest]},
            "source_endpoint": url,
            "prior_game_count": len(latest),
        }
