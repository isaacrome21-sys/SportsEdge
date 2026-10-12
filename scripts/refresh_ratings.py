#!/usr/bin/env python3
"""Refresh the persisted Elo rating stores from free public endpoints.

Free sources only, no keys, no market prices:
* NFL / CFB / NBA — ESPN scoreboard (site.api.espn.com)
* MLB            — MLB StatsAPI schedule (statsapi.mlb.com)

Writes one JSON store per sport to ``data/ratings/<sport>.json`` (repo
root). The RUN IT path loads these stores via
``RatingProvider.load`` / ``configure`` — it never fetches history itself.

This is an offline data-side job. Isaac runs nothing: the coordinator's
data pipeline runs it on a schedule, or a maintainer runs it manually.

Usage (from the repo root of the elo branch)::

    PYTHONPATH=~/workspace/sportsedge-elo \\
        python3 scripts/refresh_ratings.py [--sports NFL,MLB] [--out-dir data/ratings]

Research only. Fail closed: any malformed game aborts that sport's store
rather than writing a partial file.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from sportsedge.ratings import RatingProvider  # noqa: E402
from sportsedge.ratings.history import GameRecord, season_label  # noqa: E402

ESPN = "https://site.api.espn.com/apis/site/v2/sports"
ESPN_LEAGUE = {"NFL": "football/nfl", "CFB": "football/college-football",
               "NBA": "basketball/nba"}
MLB_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"


def _get_json(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "SportsEdge-research/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _clock(value: str) -> datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def espn_day_games(sport: str, stamp: str) -> list[GameRecord]:
    url = f"{ESPN}/{ESPN_LEAGUE[sport]}/scoreboard?dates={stamp}"
    data = _get_json(url)
    return _parse_espn(sport, data.get("events") or [])


def _parse_espn(sport: str, events: list) -> list[GameRecord]:
    games = []
    for event in events:
        if not isinstance(event, dict):
            continue
        stype = ((event.get("status") or {}).get("type") or {})
        if stype.get("completed") is not True:
            continue
        comps = event.get("competitions") or []
        if not comps or not isinstance(comps[0], dict):
            continue
        competitors = comps[0].get("competitors") or []
        home = next((c for c in competitors
                     if isinstance(c, dict) and c.get("homeAway") == "home"), None)
        away = next((c for c in competitors
                     if isinstance(c, dict) and c.get("homeAway") == "away"), None)
        if home is None or away is None:
            raise ValueError("REFRESH_COMPETITORS_UNVERIFIED:" + str(event.get("id")))
        try:
            hs, aws = int(home.get("score")), int(away.get("score"))
        except (TypeError, ValueError) as exc:
            raise ValueError("REFRESH_SCORE_UNVERIFIED:" + str(event.get("id"))) from exc
        kickoff = _clock(str(event.get("date")))
        games.append(GameRecord(
            kickoff=kickoff,
            home=str((home.get("team") or {}).get("displayName") or "").strip(),
            away=str((away.get("team") or {}).get("displayName") or "").strip(),
            home_score=hs, away_score=aws,
            season=season_label(sport, kickoff),
            event_id=str(event.get("id") or "").strip() or None))
    return games


def mlb_month_games(year: int, month: int) -> list[GameRecord]:
    import calendar
    last = calendar.monthrange(year, month)[1]
    url = (f"{MLB_SCHEDULE}?sportId=1&startDate={year}-{month:02d}-01"
           f"&endDate={year}-{month:02d}-{last:02d}&hydrate=linescore")
    data = _get_json(url)
    games = []
    for day in data.get("dates") or []:
        for g in (day.get("games") or []):
            if str(((g.get("status") or {}).get("detailedState") or "")) != "Final":
                continue
            teams = g.get("teams") or {}
            home, away = teams.get("home") or {}, teams.get("away") or {}
            try:
                hs, aws = int(home.get("score")), int(away.get("score"))
            except (TypeError, ValueError) as exc:
                raise ValueError("REFRESH_MLB_SCORE_UNVERIFIED") from exc
            kickoff = _clock(str(g.get("gameDate")))
            games.append(GameRecord(
                kickoff=kickoff,
                home=str(((home.get("team") or {}).get("name")) or "").strip(),
                away=str(((away.get("team") or {}).get("name")) or "").strip(),
                home_score=hs, away_score=aws,
                season=season_label("MLB", kickoff),
                event_id=str(g.get("gamePk"))))
    return games


DAY_WINDOWS = {
    "NFL": [("2022-09-08", "2023-01-08"), ("2023-09-07", "2024-01-07"),
            ("2024-09-05", "2025-01-05"), ("2025-09-04", "2026-01-04")],
    "CFB": [("2022-08-27", "2022-12-10"), ("2023-08-26", "2023-12-09"),
            ("2024-08-24", "2024-12-14"), ("2025-08-23", "2026-01-19")],
    "NBA": [("2022-10-18", "2023-04-09"), ("2023-10-24", "2024-04-14"),
            ("2024-10-22", "2025-04-13")],
}


def collect(sport: str) -> list[GameRecord]:
    """History windows: 2022 through the current date (regular seasons).

    NOTE: ESPN's scoreboard ignores the legacy ?season=&week= params (it
    returns the current season), so history is collected per day with
    ?dates=YYYYMMDD.
    """
    games: list[GameRecord] = []
    if sport in DAY_WINDOWS:
        for start, end in DAY_WINDOWS[sport]:
            day = datetime.strptime(start, "%Y-%m-%d").date()
            last = datetime.strptime(end, "%Y-%m-%d").date()
            today = datetime.now(timezone.utc).date()
            if day > today:
                continue
            last = min(last, today)
            while day <= last:
                stamp = day.strftime("%Y%m%d")
                try:
                    games.extend(espn_day_games(sport, stamp))
                except Exception as exc:  # one bad day must not poison the store
                    print(f"  [warn] {sport} {stamp}: {exc}", file=sys.stderr)
                day += timedelta(days=1)
                time.sleep(0.2)
    elif sport == "MLB":
        for year in (2022, 2023, 2024, 2025):
            for month in range(4, 11):
                games.extend(mlb_month_games(year, month))
                time.sleep(0.25)
    else:
        raise ValueError("REFRESH_SPORT_UNSUPPORTED:" + sport)
    games.sort(key=lambda g: g.kickoff)
    return games


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sports", default="NFL,CFB,NBA,MLB")
    ap.add_argument("--out-dir", default=str(REPO / "data" / "ratings"))
    args = ap.parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for sport in [s.strip().upper() for s in args.sports.split(",") if s.strip()]:
        print(f"== {sport}: collecting verified history", flush=True)
        games = collect(sport)
        print(f"== {sport}: {len(games)} games; building provider", flush=True)
        provider = RatingProvider(sport)
        provider.record_games(games)  # raises on any malformed game
        path = provider.save(out_dir / f"{sport.lower()}.json")
        print(f"== {sport}: wrote {path} "
              f"({provider.tracker.games_recorded} games, "
              f"{len(provider.tracker.teams())} teams)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
