"""Verified public MLB first-inning history from free StatsAPI linescores.

Only free MLB StatsAPI endpoints are used: schedule (hydrate=linescore,
probablePitcher), boxscore-free team histories, and play-by-play for the
starter first-inning split (IN_BUILD, not applied to pricing). No sportsbook
odds, no league priors, no caller-supplied features. Research only.

Fail-closed discipline: a game whose linescore is missing or malformed is
skipped and counted (never imputed); a fixture that cannot be uniquely
verified raises. Started games are rejected for pregame pricing.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = "https://statsapi.mlb.com/api/v1"
SCHEDULE = ROOT + "/schedule"

FIRST_INNING_DATA_VERSION = "mlb_first_inning_data_linescore_v1"


class FirstInningDataError(ValueError):
    pass


def _norm(value):
    latin = unicodedata.normalize("NFKD", str(value or ""))
    folded = "".join(ch for ch in latin if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", folded.lower()).split())


def _clock(value, name):
    try:
        d = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise FirstInningDataError(name + "_UNVERIFIED") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise FirstInningDataError(name + "_TIMEZONE_REQUIRED")
    return d.astimezone(timezone.utc)


def _public_json(url):
    if not str(url).startswith(ROOT + "/"):
        raise FirstInningDataError("PUBLIC_MLB_ENDPOINT_REQUIRED")
    try:
        request = Request(url, headers={"User-Agent": "SportsEdge-free-research/1.0",
                                        "Accept": "application/json"})
        with urlopen(request, timeout=25) as response:
            if response.status != 200:
                return None
            data = json.loads(response.read(12_000_000))
            return data if isinstance(data, dict) else None
    except (OSError, ValueError, TimeoutError, json.JSONDecodeError):
        return None


class MLBFirstInningPublicSource:
    """Cached verified StatsAPI access for first-inning histories."""

    def __init__(self, *, getter=None, cache_dir=None):
        self.getter = getter or _public_json
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.cache = {}

    def _fetch(self, url):
        if url in self.cache:
            return self.cache[url]
        data = None
        if self.cache_dir is not None:
            key = hashlib.sha1(url.encode("utf-8")).hexdigest()
            path = self.cache_dir / (key + ".json")
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    raise FirstInningDataError("FIRST_INNING_CACHE_CORRUPT:" + key) from exc
        if data is None:
            try:
                data = self.getter(url)
            except (OSError, ValueError, TypeError, TimeoutError):
                data = None
            if not isinstance(data, dict):
                data = None
            elif self.cache_dir is not None:
                try:
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    (self.cache_dir / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".json")
                     ).write_text(json.dumps(data), encoding="utf-8")
                except OSError:
                    pass
        self.cache[url] = data
        return data

    def schedule_chunk(self, start_date, end_date):
        """Fetch schedule with linescore + probablePitcher hydration."""
        url = SCHEDULE + "?" + urlencode({
            "sportId": "1",
            "startDate": start_date,
            "endDate": end_date,
            "hydrate": "linescore,probablePitcher",
        })
        data = self._fetch(url)
        if not isinstance(data, dict) or not isinstance(data.get("dates"), list):
            raise FirstInningDataError("FIRST_INNING_SCHEDULE_UNAVAILABLE")
        return data["dates"]

    def schedule_range(self, start_date, end_date, *, chunk_days=7):
        """Yield schedule date-blocks over [start_date, end_date] (YYYY-MM-DD)."""
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
        if end < start:
            raise FirstInningDataError("FIRST_INNING_DATE_RANGE_INVALID")
        cursor = start
        while cursor <= end:
            chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
            yield self.schedule_chunk(cursor.isoformat(), chunk_end.isoformat())
            cursor = chunk_end + timedelta(days=1)


def _nonneg_int(value):
    if isinstance(value, bool):
        return None
    try:
        n = int(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return n if n >= 0 else None


def parse_completed_linescore_game(game):
    """Parse one schedule game -> verified first-inning + hits record.

    Returns None for games that must be skipped (not Final, or missing
    first-inning linescore). Raises FirstInningDataError on corrupt identity.
    """
    if not isinstance(game, dict):
        return None
    if str(((game.get("status") or {}).get("detailedState") or "")) != "Final":
        return None
    game_pk = game.get("gamePk")
    game_date = str(game.get("gameDate") or "").strip()
    if game_pk is None or not game_date:
        raise FirstInningDataError("FIRST_INNING_GAME_IDENTITY_UNVERIFIED")
    _clock(game_date, "FIRST_INNING_KICKOFF")
    teams = game.get("teams") or {}
    away = teams.get("away") or {}
    home = teams.get("home") or {}
    away_team = away.get("team") or {}
    home_team = home.get("team") or {}
    away_id = away_team.get("id")
    home_id = home_team.get("id")
    if away_id is None or home_id is None:
        raise FirstInningDataError("FIRST_INNING_TEAM_IDENTITY_UNVERIFIED")
    linescore = game.get("linescore") or {}
    innings = linescore.get("innings")
    if not isinstance(innings, list) or not innings:
        return None
    first = next((i for i in innings
                  if isinstance(i, dict) and i.get("num") == 1), None)
    if first is None:
        return None
    a1 = first.get("away") or {}
    h1 = first.get("home") or {}
    inn1_away_runs = _nonneg_int(a1.get("runs"))
    inn1_home_runs = _nonneg_int(h1.get("runs"))
    inn1_away_hits = _nonneg_int(a1.get("hits"))
    inn1_home_hits = _nonneg_int(h1.get("hits"))
    if (inn1_away_runs is None or inn1_home_runs is None
            or inn1_away_hits is None or inn1_home_hits is None):
        return None
    totals = linescore.get("teams") or {}
    t_away = totals.get("away") or {}
    t_home = totals.get("home") or {}
    game_away_hits = _nonneg_int(t_away.get("hits"))
    game_home_hits = _nonneg_int(t_home.get("hits"))
    if game_away_hits is None or game_home_hits is None:
        return None

    def _probable(side):
        info = (teams.get(side) or {}).get("probablePitcher") or {}
        pid = info.get("id")
        name = str(info.get("fullName") or "").strip()
        if pid is None or not name:
            return None
        return {"id": int(pid), "name": name}

    return {
        "game_pk": str(game_pk),
        "game_date": game_date,
        "game_type": str(game.get("gameType") or "").strip(),
        "away_id": int(away_id),
        "away_name": str(away_team.get("name") or "").strip(),
        "home_id": int(home_id),
        "home_name": str(home_team.get("name") or "").strip(),
        "inn1_away_runs": inn1_away_runs,
        "inn1_home_runs": inn1_home_runs,
        "inn1_away_hits": inn1_away_hits,
        "inn1_home_hits": inn1_home_hits,
        "game_away_hits": game_away_hits,
        "game_home_hits": game_home_hits,
        "probable_away_pitcher": _probable("away"),
        "probable_home_pitcher": _probable("home"),
    }


def collect_completed_games(dates, *, game_types=("R",)):
    """Parse schedule date-blocks -> (games, skipped) with fail-closed skips."""
    games, skipped = [], 0
    for block in dates:
        if not isinstance(block, dict):
            skipped += 1
            continue
        for game in block.get("games") or []:
            try:
                parsed = parse_completed_linescore_game(game)
            except FirstInningDataError:
                skipped += 1
                continue
            if parsed is None:
                skipped += 1
                continue
            if game_types and parsed["game_type"] not in game_types:
                skipped += 1
                continue
            games.append(parsed)
    games.sort(key=lambda g: (g["game_date"], g["game_pk"]))
    return games, skipped


def build_team_histories(games):
    """Per-team chronological game records for strictly-prior pooling."""
    histories = {}
    for game in games:
        when = game["game_date"]
        for side, was_home in (("away", False), ("home", True)):
            team_id = game[side + "_id"]
            if was_home:
                inn1_for = game["inn1_home_runs"]
                inn1_against = game["inn1_away_runs"]
                inn1_hits_for = game["inn1_home_hits"]
                inn1_hits_against = game["inn1_away_hits"]
                game_hits_for = game["game_home_hits"]
                game_hits_against = game["game_away_hits"]
            else:
                inn1_for = game["inn1_away_runs"]
                inn1_against = game["inn1_home_runs"]
                inn1_hits_for = game["inn1_away_hits"]
                inn1_hits_against = game["inn1_home_hits"]
                game_hits_for = game["game_away_hits"]
                game_hits_against = game["game_home_hits"]
            entry = histories.setdefault(team_id, {
                "team_id": team_id,
                "team_name": game[side + "_name"],
                "games": [],
            })
            entry["games"].append({
                "game_pk": game["game_pk"],
                "game_date": when,
                "was_home": was_home,
                "inn1_for": inn1_for,
                "inn1_against": inn1_against,
                "inn1_hits_for": inn1_hits_for,
                "inn1_hits_against": inn1_hits_against,
                "game_hits_for": game_hits_for,
                "game_hits_against": game_hits_against,
            })
    for entry in histories.values():
        entry["games"].sort(key=lambda g: (g["game_date"], g["game_pk"]))
        entry["team_name"] = entry["games"][-1].get("team_name_hint", "") or entry["team_name"]
    return histories


def prior_pools(histories, team_id, *, was_home, before_iso, max_games=30):
    """Strictly-prior pools for a team in a venue role.

    Returns dict of stat -> list[int] (most recent last, capped at
    max_games). Only games with game_date strictly before before_iso count.
    """
    entry = histories.get(team_id)
    if entry is None:
        raise FirstInningDataError("FIRST_INNING_TEAM_HISTORY_MISSING")
    prior = [g for g in entry["games"]
             if g["was_home"] is was_home and g["game_date"] < before_iso]
    recent = prior[-max_games:]
    pools = {}
    for stat in ("inn1_for", "inn1_against", "inn1_hits_for",
                 "inn1_hits_against", "game_hits_for", "game_hits_against"):
        pools[stat] = [g[stat] for g in recent]
    pools["game_count"] = len(recent)
    return pools


def resolve_pregame_fixture(*, away, home, kickoff, now, source):
    """Verify a unique not-yet-started fixture from the public schedule.

    Returns {game_pk, kickoff_utc, away_id, home_id, probable pitchers}.
    Mirrors the batter-history fixture discipline: unique match, 2h window.
    """
    now_utc = _clock(now, "MODEL_AS_OF")
    proposed = _clock(kickoff, "OWNER_GAME_START")
    if proposed <= now_utc:
        raise FirstInningDataError("STARTED_GAME_REQUIRES_VERIFIED_LIVE_PROP_ENGINE")
    selected = []
    for date in {(proposed - timedelta(days=1)).date(), proposed.date()}:
        for block in source.schedule_chunk(date.isoformat(), date.isoformat()):
            for game in block.get("games") or []:
                teams = game.get("teams") or {}
                a = ((teams.get("away") or {}).get("team") or {}).get("name")
                h = ((teams.get("home") or {}).get("team") or {}).get("name")
                if _norm(a) != _norm(away) or _norm(h) != _norm(home):
                    continue
                try:
                    start = _clock(game.get("gameDate"), "MLB_SCHEDULE_START")
                except FirstInningDataError:
                    continue
                if abs((start - proposed).total_seconds()) > 2 * 3600:
                    continue
                selected.append(game)
    unique = {str(g.get("gamePk")): g for g in selected if g.get("gamePk")}
    if len(unique) != 1:
        raise FirstInningDataError("MLB_PUBLIC_FIXTURE_NOT_UNIQUELY_VERIFIED")
    game = next(iter(unique.values()))
    kickoff_utc = _clock(game.get("gameDate"), "MLB_SCHEDULE_START")
    if kickoff_utc <= now_utc:
        raise FirstInningDataError("STARTED_GAME_REQUIRES_VERIFIED_LIVE_PROP_ENGINE")
    teams = game.get("teams") or {}
    away_id = ((teams.get("away") or {}).get("team") or {}).get("id")
    home_id = ((teams.get("home") or {}).get("team") or {}).get("id")
    if away_id is None or home_id is None:
        raise FirstInningDataError("FIRST_INNING_FIXTURE_TEAM_IDENTITY_UNVERIFIED")

    def _probable(side):
        info = (teams.get(side) or {}).get("probablePitcher") or {}
        pid = info.get("id")
        name = str(info.get("fullName") or "").strip()
        return {"id": int(pid), "name": name} if pid is not None and name else None

    return {
        "game_pk": str(game.get("gamePk")),
        "kickoff_utc": kickoff_utc.isoformat(),
        "away_id": int(away_id),
        "home_id": int(home_id),
        "away_name": str((((teams.get("away") or {}).get("team") or {}).get("name")) or ""),
        "home_name": str((((teams.get("home") or {}).get("team") or {}).get("name")) or ""),
        "probable_away_pitcher": _probable("away"),
        "probable_home_pitcher": _probable("home"),
        "schedule_endpoint": SCHEDULE,
    }


# ---------------------------------------------------------------------------
# Starter first-inning history from verified gameLogs + linescores.
#
# For each verified prior START (gameLog gamesStarted == 1), the starter's
# 1st-inning runs allowed are read from the verified linescore of that game:
# the batting side's 1st-inning runs in the half the starter pitched.
# Approximation (documented): all 1st-inning runs are attributed to the
# starter; mid-1st pitching changes are rare and add only noise.
# ---------------------------------------------------------------------------

MIN_STARTER_STARTS = 5
MAX_STARTER_STARTS = 15


def pitcher_prior_starts(pitcher_id, *, seasons, source):
    """Verified starts for a pitcher: [{game_pk, date, team_id}]."""
    starts = []
    for season in seasons:
        url = (ROOT + f"/people/{int(pitcher_id)}/stats?stats=gameLog&group=pitching&"
               + urlencode({"season": str(int(season))}))
        data = source._fetch(url)
        if not isinstance(data, dict) or not isinstance(data.get("stats"), list):
            continue
        for stat in data["stats"]:
            if not isinstance(stat, dict):
                continue
            for row in stat.get("splits") or []:
                if not isinstance(row, dict):
                    continue
                if str(row.get("gameType") or "") != "R":
                    continue
                stat_block = row.get("stat") or {}
                if stat_block.get("gamesStarted") != 1:
                    continue
                game_pk = (row.get("game") or {}).get("gamePk")
                date = str(row.get("date") or "").strip()
                team_id = (row.get("team") or {}).get("id")
                if game_pk is None or not date or team_id is None:
                    continue
                starts.append({"game_pk": str(game_pk), "date": date,
                               "team_id": int(team_id)})
    starts.sort(key=lambda s: (s["date"], s["game_pk"]))
    return starts


def starter_first_inning_allowed(pitcher_id, *, before_date, games_by_pk,
                                 source, seasons=(2024, 2025),
                                 max_starts=MAX_STARTER_STARTS,
                                 min_starts=MIN_STARTER_STARTS):
    """1st-inning runs allowed per verified prior start (most recent last).

    Raises FirstInningDataError when fewer than min_starts prior starts can
    be verified against the linescore collection.
    """
    prior = [s for s in pitcher_prior_starts(pitcher_id, seasons=seasons,
                                            source=source)
             if s["date"] < before_date][-max_starts:]
    allowed = []
    for start in prior:
        game = games_by_pk.get(start["game_pk"])
        if game is None:
            continue
        if start["team_id"] == game["away_id"]:
            allowed.append(game["inn1_home_runs"])   # pitched bottom-1
        elif start["team_id"] == game["home_id"]:
            allowed.append(game["inn1_away_runs"])    # pitched top-1
        else:
            continue  # traded mid-history; team mismatch -> skip, never guess
    if len(allowed) < min_starts:
        raise FirstInningDataError(
            f"STARTER_FIRST_INNING_HISTORY_INSUFFICIENT:{pitcher_id}")
    return allowed


# ---------------------------------------------------------------------------
# Starter first-inning split (IN_BUILD): verified via play-by-play, but NOT
# applied to pricing until it passes the backtest harness. Kept here so the
# data path is real, tested, and fail-closed rather than a stub.
# ---------------------------------------------------------------------------

def starter_first_inning_allowed_from_pbp(pitcher_id, *, game_pks, getter=None,
                                 max_starts=15):
    """First-inning runs allowed by a verified starter across prior starts.

    For each prior start (gamePk), reads the verified play-by-play, finds the
    first half-inning the pitcher threw in the 1st, and counts runs allowed
    from the play result scores. Returns {"starts": [...], "runs_allowed": n}.
    IN_BUILD: not consumed by pricing yet.
    """
    get = getter or _public_json
    starts = []
    for game_pk in list(game_pks)[:max_starts]:
        url = ROOT + f"/game/{game_pk}/playByPlay"
        try:
            data = get(url)
        except (OSError, ValueError, TypeError, TimeoutError):
            continue
        if not isinstance(data, dict):
            continue
        plays = data.get("allPlays")
        if not isinstance(plays, list):
            continue
        first_inning_plays = [
            p for p in plays
            if isinstance(p, dict)
            and isinstance(p.get("about"), dict)
            and p["about"].get("inning") == 1
            and isinstance(p.get("matchup"), dict)
            and isinstance((p["matchup"].get("pitcher") or {}).get("id"), int)
        ]
        if not first_inning_plays:
            continue
        # The starter is the pitcher of the first 1st-inning plate appearance
        # in the half his team pitched.
        starter_half = None
        for half in ("top", "bottom"):
            half_plays = [p for p in first_inning_plays
                          if p["about"].get("halfInning") == half]
            if not half_plays:
                continue
            first_pitcher = half_plays[0]["matchup"]["pitcher"]["id"]
            if int(first_pitcher) == int(pitcher_id):
                starter_half = half
                break
        if starter_half is None:
            continue
        mine = [p for p in first_inning_plays
                if p["about"].get("halfInning") == starter_half
                and int(p["matchup"]["pitcher"]["id"]) == int(pitcher_id)]
        if not mine:
            continue
        score_key = "homeScore" if starter_half == "bottom" else "awayScore"
        scores = []
        for p in mine:
            result = p.get("result") or {}
            for key in ("homeScore", "awayScore"):
                value = _nonneg_int(result.get(key))
                if value is not None:
                    scores.append((key, value))
        half_scores = [v for k, v in scores if k == score_key]
        if len(half_scores) < 2:
            continue
        # Runs allowed while he pitched = score increase across his plays.
        # Plays are chronological; take last minus first observed.
        runs = max(0, half_scores[-1] - half_scores[0])
        starts.append({"game_pk": str(game_pk), "half": starter_half,
                       "runs_allowed": runs})
    if not starts:
        raise FirstInningDataError("STARTER_FIRST_INNING_SPLIT_UNVERIFIED")
    return {
        "pitcher_id": int(pitcher_id),
        "starts": starts,
        "n_starts": len(starts),
        "runs_allowed": [s["runs_allowed"] for s in starts],
        "status": "IN_BUILD_NOT_APPLIED_TO_PRICING",
    }
