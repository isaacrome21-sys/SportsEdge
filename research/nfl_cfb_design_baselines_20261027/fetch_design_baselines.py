#!/usr/bin/env python3
"""Fetch and hash-pin the NFL/CFB DESIGN baselines (see DESIGN_BASELINES_PIN_RECORD.md).

DESIGN DATA ONLY. Nothing fetched by this script is validation evidence, and
no comparison against these untimestamped closes may be labeled verified CLV.

Sources:
  * nflverse schedules release (games.csv.gz) -- no key required.
  * CollegeFootballData (CFBD) betting lines, 2013+ -- requires a CFBD key in
    the environment (SPORTSEDGE_CFBD_API_KEY, CFBD_API_KEY, or
    CFB_SDV_CFBD_API_KEY). The key value is never printed, logged, or written.

Usage:
    python3 fetch_design_baselines.py [--out-dir DIR] [--cfbd-years 2013-2025]

With no CFBD key present, the nflverse leg still runs and the CFBD leg reports
BLOCKED (documented-only) instead of failing.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

NFLVERSE_SCHEDULES_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "schedules/games.csv.gz"
)
CFBD_LINES_URL = "https://api.collegefootballdata.com/lines"
CFBD_KEY_ENV_NAMES = (
    "SPORTSEDGE_CFBD_API_KEY",
    "CFBD_API_KEY",
    "CFB_SDV_CFBD_API_KEY",
)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_bytes(url: str, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req) as resp:  # noqa: S310 - fixed HTTPS hosts
        return resp.read()


def pin_nflverse(out_dir: str) -> dict:
    raw = fetch_bytes(NFLVERSE_SCHEDULES_URL)
    rows = list(csv.DictReader(io.StringIO(gzip.decompress(raw).decode("utf-8"))))
    seasons = sorted({int(r["season"]) for r in rows})
    path = os.path.join(out_dir, "nflverse_games.csv.gz")
    with open(path, "wb") as fh:
        fh.write(raw)
    return {
        "dataset": "nflverse schedules (games.csv.gz)",
        "source_url": NFLVERSE_SCHEDULES_URL,
        "file": "nflverse_games.csv.gz",
        "sha256": sha256_hex(raw),
        "bytes": len(raw),
        "rows": len(rows),
        "coverage_seasons": [seasons[0], seasons[-1]],
        "status": "HASH_VERIFIED_PULL",
    }


def cfbd_key() -> str | None:
    for name in CFBD_KEY_ENV_NAMES:
        value = os.environ.get(name)
        if value:
            return value
    return None


def pin_cfbd(out_dir: str, years: range) -> dict:
    key = cfbd_key()
    if not key:
        return {
            "dataset": "CFBD betting lines",
            "source_url": CFBD_LINES_URL,
            "status": "DOCUMENTED_ONLY",
            "blocker": "CFBD key (env) not present in this execution environment",
        }
    headers = {"Authorization": f"Bearer {key}"}
    out_path = os.path.join(out_dir, "cfbd_lines.csv")
    total_games = 0
    total_line_rows = 0
    year_stats: dict[str, dict] = {}
    with open(out_path, "w", newline="") as fh:
        writer = None
        for year in years:
            raw = fetch_bytes(f"{CFBD_LINES_URL}?year={year}", headers=headers)
            games = json.loads(raw.decode("utf-8"))
            year_games = 0
            year_rows = 0
            for game in games:
                year_games += 1
                for line in game.get("lines") or []:
                    row = {
                        "game_id": game.get("id"),
                        "season": game.get("season"),
                        "week": game.get("week"),
                        "start_date": game.get("startDate"),
                        "home_team": game.get("homeTeam"),
                        "away_team": game.get("awayTeam"),
                        "home_score": game.get("homeScore"),
                        "away_score": game.get("awayScore"),
                        "provider": line.get("provider"),
                        "spread": line.get("spread"),
                        "spread_open": line.get("spreadOpen"),
                        "over_under": line.get("overUnder"),
                        "over_under_open": line.get("overUnderOpen"),
                        "home_moneyline": line.get("homeMoneyline"),
                        "away_moneyline": line.get("awayMoneyline"),
                    }
                    if writer is None:
                        writer = csv.DictWriter(fh, fieldnames=list(row.keys()))
                        writer.writeheader()
                    writer.writerow(row)
                    year_rows += 1
            year_stats[str(year)] = {
                "games": year_games,
                "line_rows": year_rows,
                "raw_json_sha256": sha256_hex(raw),
            }
            total_games += year_games
            total_line_rows += year_rows
    with open(out_path, "rb") as fh:
        csv_bytes = fh.read()
    return {
        "dataset": "CFBD betting lines",
        "source_url": CFBD_LINES_URL,
        "file": "cfbd_lines.csv",
        "sha256": sha256_hex(csv_bytes),
        "bytes": len(csv_bytes),
        "games": total_games,
        "rows": total_line_rows,
        "per_year": year_stats,
        "status": "HASH_VERIFIED_PULL",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=".")
    parser.add_argument("--cfbd-years", default="2013-2025")
    args = parser.parse_args()
    start, end = (int(p) for p in args.cfbd_years.split("-", 1))
    retrieved = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pins = {
        "retrieved_utc": retrieved,
        "label": "DESIGN ONLY - not validation evidence; vs-close is never verified CLV",
        "datasets": [pin_nflverse(args.out_dir), pin_cfbd(args.out_dir, range(start, end + 1))],
    }
    print(json.dumps(pins, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
