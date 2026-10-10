#!/usr/bin/env python3
"""[NBA LINES] issue -> SportsEdge NBA card (markdown).

Fetches completed NBA results (ESPN public scoreboard) from Oct 1 of last season
through yesterday, replays the ratings model, prices the pasted DK lines and
writes card.md. Intake errors write intake_error.txt and exit 2.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.nba.lines_card import (  # noqa: E402
    NBALinesError, parse_lines, ratings_from_results, render, team_abbr,
)

CHICAGO = ZoneInfo("America/Chicago")
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={a}-{b}&limit=1000"
# Fallback: one request per day. The month-range query returned HTTP 400 from Actions
# on 2026-10-10 (#1826), so a 4xx on a range switches the rest of the run to per-day.
SCOREBOARD_DAY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d}"
OFFSEASON_MONTHS = (7, 8, 9)  # no regular-season/playoff games; skipped in per-day mode


class FetchError(RuntimeError):
    """Fetch failed. ``client`` is True for HTTP 4xx (do not retry; change the query)."""

    def __init__(self, msg: str, *, client: bool = False) -> None:
        super().__init__(msg)
        self.client = client


def _get(url: str) -> dict:
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (SportsEdge nba-card)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500 and exc.code != 429:
                raise FetchError(f"ESPN_FETCH_FAILED:HTTP {exc.code}", client=True) from exc
            last = exc
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(2 * (attempt + 1))
    raise FetchError(f"ESPN_FETCH_FAILED:{type(last).__name__}:{str(last)[:120]}")


def parse_events(data: dict) -> list[dict]:
    out = []
    for ev in data.get("events") or []:
        stype = (ev.get("season") or {}).get("type")
        if stype not in (2, 3, 5):  # regular, playoffs, play-in
            continue
        comp = (ev.get("competitions") or [{}])[0]
        if not ((comp.get("status") or ev.get("status") or {}).get("type") or {}).get("completed"):
            continue
        side = {}
        for c in comp.get("competitors") or []:
            try:
                side[c["homeAway"]] = (team_abbr(c["team"]["abbreviation"]), float(c["score"]))
            except (KeyError, ValueError, TypeError, NBALinesError):
                side = {}
                break
        if set(side) != {"home", "away"}:
            continue
        d = int(str(ev.get("date", ""))[:10].replace("-", "") or 0)
        out.append({"id": ev.get("id"), "season": (ev.get("season") or {}).get("year"), "date": d,
                    "home": side["home"][0], "away": side["away"][0],
                    "home_pts": side["home"][1], "away_pts": side["away"][1],
                    "neutral": bool(comp.get("neutralSite"))})
    return out


def _fetch_days(days: list[date], fetch) -> tuple[list[dict], list[str]]:
    def one(d: date):
        try:
            return d, parse_events(fetch(SCOREBOARD_DAY.format(d=d.strftime("%Y%m%d")))), None
        except RuntimeError as exc:
            return d, [], f"{d:%Y-%m-%d}: {exc}"

    games, errors = [], []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for _, evs, err in pool.map(one, days):
            games += evs
            if err:
                errors.append(err)
    return games, errors


def fetch_results(today: date, fetch=_get) -> tuple[list[dict], list[str]]:
    """Completed games from Oct 1 of last season through yesterday.

    Tries month-range queries; after the first HTTP 4xx, fetches the remaining
    in-season days one by one (ESPN rejected the range query from Actions).
    """
    start = date(today.year - 1 if today.month >= 7 else today.year - 2, 10, 1)
    games, errors, seen = [], [], set()

    def add(evs):
        for g in evs:
            if g["id"] not in seen:
                seen.add(g["id"])
                games.append(g)

    a = start
    while a < today:
        b = min(date(a.year + (a.month == 12), a.month % 12 + 1, 1) - timedelta(days=1), today - timedelta(days=1))
        try:
            add(parse_events(fetch(SCOREBOARD.format(a=a.strftime("%Y%m%d"), b=b.strftime("%Y%m%d")))))
        except FetchError as exc:
            if not exc.client:
                errors.append(f"{a:%Y-%m}: {exc}")
                a = b + timedelta(days=1)
                continue
            days, d = [], a
            while d < today:
                if d.month not in OFFSEASON_MONTHS:
                    days.append(d)
                d += timedelta(days=1)
            evs, errs = _fetch_days(days, fetch)
            add(evs)
            errors += errs
            break
        except RuntimeError as exc:
            errors.append(f"{a:%Y-%m}: {exc}")
        a = b + timedelta(days=1)
    return games, errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--observed-at", required=True)
    ap.add_argument("--issue", default="")
    ap.add_argument("--results-file", help="cached results JSON (skips ESPN)")
    ap.add_argument("--out", default="artifacts/nba/card.md")
    args = ap.parse_args()
    observed = datetime.fromisoformat(args.observed_at.replace("Z", "+00:00")).astimezone(CHICAGO)
    try:
        games = parse_lines(Path(args.body_file).read_text(encoding="utf-8"))
    except NBALinesError as exc:
        Path("intake_error.txt").write_text(str(exc) + "\n\nExpected per game:\nCeltics @ Knicks\nML +130 -155\nSpread +3.5 -110 -110\nTotal 224.5 -110 -110\n", encoding="utf-8")
        print(f"INTAKE_FAILED: {exc}")
        return 2
    if args.results_file:
        results, errors = json.loads(Path(args.results_file).read_text(encoding="utf-8")), []
    else:
        results, errors = fetch_results(observed.date())
    if len(results) < 200:
        Path("intake_error.txt").write_text(
            f"NBA_RESULTS_UNAVAILABLE: only {len(results)} completed games fetched; no card.\n" + "\n".join(errors[:15]) + (f"\n... {len(errors) - 15} more" if len(errors) > 15 else ""), encoding="utf-8")
        print("RESULTS_FAILED")
        return 3
    ratings = ratings_from_results(results)
    last = max(r["date"] for r in results)
    note = f"Ratings from {len(results)} completed games through {last}."
    if errors:
        note += f" Fetch gaps: {len(errors)} request(s) failed."
    card = render(games, ratings, observed=observed.strftime("%Y-%m-%d %H:%M CT"), results_note=note)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(card, encoding="utf-8")
    print(f"card={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
