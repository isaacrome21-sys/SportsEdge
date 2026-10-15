"""Independent public MLB probable-pitcher ID and strictly prior pitching starts.

Free MLB StatsAPI only; no sportsbook odds, probability inference, game-log
backfill or trusted caller-supplied feature flags. The scheduled probable pitcher
is *not* a confirmed lineup starter. The existing joint engine prices the pool.
Research-only model inputs. Reject unknown schema, player mismatch or live games.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import re

ROOT = "https://statsapi.mlb.com/api/v1"


class MissingMLBHistory(ValueError):
    pass


def _clock(value, name):
    try:
        d = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise MissingMLBHistory(name + "_UNVERIFIED") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise MissingMLBHistory(name + "_TIMEZONE_REQUIRED")
    return d.astimezone(timezone.utc)


def _norm(value):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


def _int(value, name):
    if isinstance(value, bool):
        raise MissingMLBHistory(name + "_INVALID")
    try:
        n = int(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise MissingMLBHistory(name + "_INVALID") from exc
    if n < 0 or str(n) != str(value).strip():
        raise MissingMLBHistory(name + "_INVALID")
    return n


def _outs(innings):
    parts = str(innings or "").split(".")
    if len(parts) != 2 or not parts[0].isdigit() or parts[1] not in {"0","1","2"}:
        raise MissingMLBHistory("MLB_INNINGS_PITCHED_FORMAT_UNVERIFIED")
    n = 3*int(parts[0]) + int(parts[1])
    if not 0 <= n <= 27:
        raise MissingMLBHistory("PITCHER_OUTS_OUTSIDE_0_27")
    return n


def public_json(url):
    if not str(url).startswith(ROOT + "/"):
        raise MissingMLBHistory("PUBLIC_MLB_ENDPOINT_REQUIRED")
    try:
        request = Request(url, headers={"User-Agent":"SportsEdge-free-research/1.0",
                                        "Accept":"application/json"})
        with urlopen(request, timeout=12) as response:
            if response.status != 200:
                return None
            data = json.loads(response.read(3_000_000))
            return data if isinstance(data, dict) else None
    except (OSError, ValueError, TimeoutError, json.JSONDecodeError):
        return None


class MLBPitcherPublicSource:
    def __init__(self, *, getter=None):
        self.getter = getter or public_json
        self.cache = {}
        self.receipts = []

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
            raise MissingMLBHistory("STARTED_GAME_REQUIRES_VERIFIED_LIVE_PROP_ENGINE")
        selected = []
        for date in {(owner_kickoff-timedelta(days=1)).date(), owner_kickoff.date()}:
            url = ROOT + "/schedule?" + urlencode({
                "sportId": "1", "date": date.isoformat(), "hydrate":"probablePitcher"})
            resp = self._fetch(url)
            if resp is None or not isinstance(resp.get("dates"), list):
                continue
            for block in resp["dates"]:
                for game in block.get("games") or []:
                    teams = game.get("teams") or {}
                    a = teams.get("away") or {}
                    h = teams.get("home") or {}
                    if (_norm((a.get("team") or {}).get("name")) != _norm(away) or
                        _norm((h.get("team") or {}).get("name")) != _norm(home)):
                        continue
                    try:
                        start = _clock(game.get("gameDate"), "MLB_SCHEDULE_START")
                    except MissingMLBHistory:
                        continue
                    if abs((start-owner_kickoff).total_seconds()) > 2*3600:
                        continue
                    selected.append(game)
        unique = {str(g.get("gamePk")): g for g in selected if g.get("gamePk")}
        if len(unique) != 1:
            raise MissingMLBHistory("MLB_PUBLIC_FIXTURE_NOT_UNIQUELY_VERIFIED")
        return next(iter(unique.values()))

    def prior_starts(self, *, away, home, player_name, owner_kickoff,
                     as_of, max_starts=12):
        """Return actual prior pitching starts and their independently sourced dates."""
        now = _clock(as_of, "MODEL_AS_OF")
        proposed = _clock(owner_kickoff, "OWNER_GAME_START")
        game = self._game(away, home, proposed, now)
        kickoff = _clock(game.get("gameDate"), "MLB_SCHEDULE_START")
        if kickoff <= now:
            raise MissingMLBHistory("STARTED_GAME_REQUIRES_VERIFIED_LIVE_PROP_ENGINE")
        selected = []
        for spot in ("away", "home"):
            probable = ((game.get("teams") or {}).get(spot) or {}).get("probablePitcher") or {}
            if _norm(probable.get("fullName")) == _norm(player_name):
                selected.append(probable)
        if len(selected) != 1:
            raise MissingMLBHistory("PLAYER_NOT_VERIFIED_AS_SCHEDULED_PROBABLE_PITCHER")
        ident = _int(selected[0].get("id"), "MLB_PITCHER_ID")
        if ident < 100:
            raise MissingMLBHistory("MLB_PITCHER_ID_UNVERIFIED")
        season = kickoff.year
        url = ROOT + f"/people/{ident}/stats?" + urlencode({
            "stats": "gameLog", "group": "pitching", "season": str(season),
        })
        data = self._fetch(url)
        if not isinstance(data, dict) or not isinstance(data.get("stats"), list):
            raise MissingMLBHistory("MLB_PITCHER_GAMELOG_UNAVAILABLE")
        splits = [v for stat in data["stats"]
                  if isinstance(stat, dict) and isinstance(stat.get("splits"), list)
                  for v in stat["splits"]]
        if not splits:
            raise MissingMLBHistory("MLB_GAMELOG_EMPTY")
        hist = []
        for row in splits:
            try:
                # A genuine start must be explicitly identified, not inferred
                # from the pitch count or the betting prop threshold.
                data_row = row["stat"]
                started = _int(data_row["gamesStarted"], "GAMES_STARTED")
                if started != 1:
                    continue
                game_id = _int((row.get("game") or {})["gamePk"], "HISTORY_GAME_PK")
                when = datetime.fromisoformat(str(row["date"])).date()
                if when >= now.date() or when >= kickoff.date():
                    continue
                stats = {
                    "strikeouts": _int(data_row["strikeOuts"],"STRIKEOUTS"),
                    "outs": _outs(data_row["inningsPitched"]),
                    "earned_runs": _int(data_row["earnedRuns"],"EARNED_RUNS"),
                    "hits_allowed": _int(data_row["hits"],"HITS"),
                    "walks_allowed": _int(data_row["baseOnBalls"],"WALKS"),
                }
                # Pitch count is a measured per-start integer in the same
                # gameLog payload; carry it only when actually present
                # (never filled with zero). A malformed value drops the
                # start via the surrounding fail-closed handler, exactly
                # like a malformed core stat.
                if "numberOfPitches" in data_row:
                    stats["pitches"] = _int(
                        data_row["numberOfPitches"], "PITCHES")
                hist.append((when, game_id, stats))
            except (ValueError, KeyError, TypeError, MissingMLBHistory):
                continue
        # Only real, distinct, completed, dated games.
        hist.sort(key=lambda x: (x[0], x[1]), reverse=True)
        latest = []
        seen = set()
        for day, pk, stats in hist:
            if pk not in seen:
                seen.add(pk)
                latest.append((day, pk, stats))
            if len(latest) == max_starts:
                break
        if len(latest) < 5:
            raise MissingMLBHistory("FEWER_THAN_FIVE_VERIFIED_PRIOR_STARTS")
        dates = [datetime.combine(day, datetime.min.time(), timezone.utc).isoformat()
                 for day, _, _ in latest]
        return {
            "game_id": str(game["gamePk"]), "pitcher_id": str(ident),
            "pitcher_name": selected[0]["fullName"], "home_team": home,
            "away_team": away,
            "kickoff_utc": kickoff.isoformat(), "source_as_of_utc": now.isoformat(),
            "prior_start_times_utc": dates,
            "features": {"history_pool": [stats for _, _, stats in latest]},
            "probable_pitcher_verified": True,
            "starter_status": "ESPN_FREE_PUBLIC_PROBABLE_ONLY_NOT_CONFIRMED_START",
            "source_endpoint": url,
            "last_prior_game_pk": latest[0][1],
            "prior_start_count": len(latest),
        }
