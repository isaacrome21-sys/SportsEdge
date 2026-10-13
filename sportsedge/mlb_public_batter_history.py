"""Independent public MLB batter plate-appearance history from free StatsAPI.

Uses only MLB StatsAPI gameLog (hitting). No sportsbook odds, no Statcast
(yet), no league priors, no trusted caller-supplied features. Research-only.
Requires a unique pregame fixture and at least 10 prior games with plate
appearances. Rejects started games and unknown schema.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import re
import unicodedata

ROOT = "https://statsapi.mlb.com/api/v1"


class MissingMLBBatterHistory(ValueError):
    pass


def _clock(value, name):
    try:
        d = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise MissingMLBBatterHistory(name + "_UNVERIFIED") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise MissingMLBBatterHistory(name + "_TIMEZONE_REQUIRED")
    return d.astimezone(timezone.utc)


def _norm(value):
    # Player names can have MLB accent marks while DK renders ASCII.
    latin = unicodedata.normalize("NFKD", str(value or ""))
    folded = "".join(ch for ch in latin if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", folded.lower()).split())


def _int(value, name):
    if isinstance(value, bool):
        raise MissingMLBBatterHistory(name + "_INVALID")
    try:
        n = int(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise MissingMLBBatterHistory(name + "_INVALID") from exc
    if n < 0 or str(n) != str(value).strip():
        raise MissingMLBBatterHistory(name + "_INVALID")
    return n


def public_json(url):
    if not str(url).startswith(ROOT + "/"):
        raise MissingMLBBatterHistory("PUBLIC_MLB_ENDPOINT_REQUIRED")
    try:
        request = Request(url, headers={"User-Agent": "SportsEdge-free-research/1.0",
                                        "Accept": "application/json"})
        with urlopen(request, timeout=12) as response:
            if response.status != 200:
                return None
            data = json.loads(response.read(3_000_000))
            return data if isinstance(data, dict) else None
    except (OSError, ValueError, TimeoutError, json.JSONDecodeError):
        return None


class MLBBatterPublicSource:
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
            raise MissingMLBBatterHistory("STARTED_GAME_REQUIRES_VERIFIED_LIVE_PROP_ENGINE")
        selected = []
        for date in {(owner_kickoff - timedelta(days=1)).date(), owner_kickoff.date()}:
            url = ROOT + "/schedule?" + urlencode({
                "sportId": "1", "date": date.isoformat()})
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
                    except MissingMLBBatterHistory:
                        continue
                    if abs((start - owner_kickoff).total_seconds()) > 2 * 3600:
                        continue
                    selected.append(game)
        unique = {str(g.get("gamePk")): g for g in selected if g.get("gamePk")}
        if len(unique) != 1:
            raise MissingMLBBatterHistory("MLB_PUBLIC_FIXTURE_NOT_UNIQUELY_VERIFIED")
        return next(iter(unique.values()))

    def prior_games(self, *, away, home, player_name, owner_kickoff,
                    as_of, max_games=30):
        """Return actual prior batting game logs for a named player."""
        now = _clock(as_of, "MODEL_AS_OF")
        proposed = _clock(owner_kickoff, "OWNER_GAME_START")
        game = self._game(away, home, proposed, now)
        kickoff = _clock(game.get("gameDate"), "MLB_SCHEDULE_START")
        if kickoff <= now:
            raise MissingMLBBatterHistory("STARTED_GAME_REQUIRES_VERIFIED_LIVE_PROP_ENGINE")

        # Prefer the official *fixture-specific* boxscore roster over
        # unrestricted MLB name search. Will Smith and Max Muncy are shared
        # names; choose an ID only when the verified game's roster makes the
        # identity unique. This is source identity, never user-claimed status.
        boxscore_url = ROOT + f"/game/{game['gamePk']}/boxscore"
        box = self._fetch(boxscore_url)
        lineup_people = []
        if isinstance(box, dict) and isinstance(box.get("teams"), dict):
            for spot in ("away", "home"):
                expected = away if spot == "away" else home
                team_meta = ((game.get("teams") or {}).get(spot) or {}).get("team") or {}
                if _norm(team_meta.get("name")) != _norm(expected):
                    raise MissingMLBBatterHistory("GAME_TEAM_MISMATCH")
                players = (box["teams"].get(spot) or {}).get("players") or {}
                if not isinstance(players, dict):
                    continue
                for key, player in players.items():
                    if not isinstance(player, dict):
                        continue
                    person = player.get("person") or {}
                    full = str(person.get("fullName") or "")
                    if _norm(full) != _norm(player_name):
                        continue
                    ident_candidate = _int(person.get("id"), "MLB_BOXSCORE_PLAYER_ID")
                    if str(key) != "ID" + str(ident_candidate):
                        raise MissingMLBBatterHistory("BOXSCORE_PLAYER_ID_CONFLICT")
                    order = player.get("battingOrder")
                    starting = isinstance(order, str) and order.isdigit() and int(order) >= 100
                    lineup_people.append((ident_candidate, full, spot, starting))
        unique_ids = {x[0] for x in lineup_people}
        if len(unique_ids) > 1:
            raise MissingMLBBatterHistory("PLAYER_NAME_AMBIGUOUS_IN_VERIFIED_GAME")
        if len(unique_ids) == 1:
            ident, resolved_name, _side, starter = lineup_people[0]
            if len(lineup_people) != 1:
                raise MissingMLBBatterHistory("PLAYER_DUPLICATE_IN_VERIFIED_GAME")
            lineup_verified = bool(starter)
        else:
            # If MLB hasn't published a roster, allow an unambiguous player
            # search only for historical research. Lineup stays UNCONFIRMED
            # even if the owner screenshot asserts otherwise.
            search_url = ROOT + "/people/search?" + urlencode({
                "names": player_name, "sportIds": "1"})
            search = self._fetch(search_url)
            people = (search or {}).get("people") or []
            matches = [p for p in people
                       if isinstance(p, dict) and _norm(p.get("fullName")) == _norm(player_name)]
            if len(matches) != 1:
                raise MissingMLBBatterHistory("PLAYER_NOT_UNIQUELY_RESOLVED_FROM_PUBLIC_SEARCH")
            ident = _int(matches[0].get("id"), "MLB_BATTER_ID")
            resolved_name = matches[0]["fullName"]
            lineup_verified = False

        season = kickoff.year
        url = ROOT + f"/people/{ident}/stats?" + urlencode({
            "stats": "gameLog", "group": "hitting", "season": str(season),
        })
        data = self._fetch(url)
        if not isinstance(data, dict) or not isinstance(data.get("stats"), list):
            raise MissingMLBBatterHistory("MLB_BATTER_GAMELOG_UNAVAILABLE")
        splits = [v for stat in data["stats"]
                  if isinstance(stat, dict) and isinstance(stat.get("splits"), list)
                  for v in stat["splits"]]
        if not splits:
            raise MissingMLBBatterHistory("MLB_BATTER_GAMELOG_EMPTY")

        hist = []
        for row in splits:
            try:
                data_row = row["stat"]
                pa = _int(data_row["plateAppearances"], "PLATE_APPEARANCES")
                if pa < 1:
                    continue
                game_id = _int((row.get("game") or {})["gamePk"], "HISTORY_GAME_PK")
                when = datetime.fromisoformat(str(row["date"])).date()
                if when >= now.date() or when >= kickoff.date():
                    continue
                # A valid appearance is not the same as a fully observed
                # market-specific outcome. Retain independently verified
                # prior games with PA + game identity/date; parse every
                # actually present stat, but NEVER fill missing with zero.
                # The empirical pricer requires the chosen market's field
                # in every retained game and fails closed otherwise.
                # Requiring totalBases (or any other market's statistic)
                # to retain a HITS appearance silently discarded otherwise
                # usable history for unrelated markets.
                stats = {"plate_appearances": pa}
                for raw_field, output_field in (
                    ("hits", "hits"), ("totalBases", "total_bases"),
                    ("rbi", "rbi"), ("runs", "runs"),
                    ("homeRuns", "home_runs"),
                    ("stolenBases", "stolen_bases"),
                    ("baseOnBalls", "walks"), ("strikeOuts", "strikeouts"),
                    ("doubles", "doubles"), ("triples", "triples"),
                ):
                    if raw_field in data_row:
                        stats[output_field] = _int(
                            data_row[raw_field], output_field.upper())
                if all(k in stats for k in (
                        "hits", "doubles", "triples", "home_runs")):
                    singles = (stats["hits"] - stats["doubles"]
                               - stats["triples"] - stats["home_runs"])
                    if singles < 0:
                        raise MissingMLBBatterHistory("INCONSISTENT_EXTRA_BASE_HIT_COUNTS")
                    stats["singles"] = singles
                if all(k in stats for k in ("hits", "runs", "rbi")):
                    stats["hits_runs_rbis"] = (
                        stats["hits"] + stats["runs"] + stats["rbi"])
                hist.append((when, game_id, stats))
            except (ValueError, KeyError, TypeError, MissingMLBBatterHistory):
                continue

        hist.sort(key=lambda x: (x[0], x[1]), reverse=True)
        latest = []
        seen = set()
        for day, pk, stats in hist:
            if pk not in seen:
                seen.add(pk)
                latest.append((day, pk, stats))
            if len(latest) == max_games:
                break
        if len(latest) < 10:
            raise MissingMLBBatterHistory("FEWER_THAN_TEN_VERIFIED_PRIOR_GAMES")
        if sum(stats["plate_appearances"] for _, _, stats in latest) < 20:
            raise MissingMLBBatterHistory("FEWER_THAN_TWENTY_PRIOR_PLATE_APPEARANCES")
        dates = [datetime.combine(day, datetime.min.time(), timezone.utc).isoformat()
                 for day, _, _ in latest]
        return {
            "game_id": str(game["gamePk"]), "batter_id": str(ident),
            "batter_name": resolved_name, "home_team": home,
            "away_team": away,
            "kickoff_utc": kickoff.isoformat(), "source_as_of_utc": now.isoformat(),
            "prior_game_times_utc": dates,
            "features": {"pa_history": [stats for _, _, stats in latest]},
            "lineup_verified": lineup_verified,
            "lineup_status": ("PUBLIC_BOXSCORE_STARTER_VERIFIED" if lineup_verified
                              else "PUBLIC_BOXSCORE_LINEUP_NOT_VERIFIED"),
            "boxscore_endpoint": boxscore_url,
            "source_endpoint": url,
            "prior_game_count": len(latest),
            "prior_plate_appearances": sum(stats["plate_appearances"] for _, _, stats in latest),
        }
