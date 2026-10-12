"""Run the participation collectors over the measured seasons and build
the coverage table.

Usage:
    python3 -m sportsedge.participation.run_collection \
        --raw-dir data/participation_raw \
        --archive-dir data/participation_archive \
        --coverage-json sportsedge/participation/coverage_measured.json

Raw payloads are read from --raw-dir when present (files named
``<signal>_<season>.csv`` plus ``games.csv``) and downloaded from the
nflverse releases otherwise. Every payload is stored into the archive
(raw-first) by the collectors themselves, with receipts.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .archive import ParticipationArchive
from .collectors import (
    GAMES_URL,
    URL_TEMPLATES,
    build_pfr_gsis_bridge,
    collect_depth_charts,
    collect_injuries,
    collect_rosters,
    collect_snap_counts,
    download,
    load_schedule,
)
from .coverage import ALL_MEASURED_SEASONS, compute_all

SIGNALS = ("injuries", "snap_counts", "weekly_rosters", "depth_charts")
FILE_NAMES = {
    "injuries": "injuries_{season}.csv",
    "snap_counts": "snap_counts_{season}.csv",
    "weekly_rosters": "roster_weekly_{season}.csv",
    "depth_charts": "depth_charts_{season}.csv",
}


def _get_raw(raw_dir: Path, name: str, season: int | None) -> tuple[bytes, str]:
    if season is None:
        local = raw_dir / "games.csv"
        url = GAMES_URL
    else:
        local = raw_dir / FILE_NAMES[name].format(season=season)
        url = URL_TEMPLATES[name].format(season=season)
    if local.exists() and local.stat().st_size > 0:
        return local.read_bytes(), url
    data = download(url)
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(data)
    return data, url


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default="data/participation_raw")
    ap.add_argument("--archive-dir", default="data/participation_archive")
    ap.add_argument("--coverage-json", default=None)
    ap.add_argument("--seasons", default=",".join(str(s) for s in ALL_MEASURED_SEASONS))
    ap.add_argument("--skip-archive", action="store_true",
                    help="compute coverage only, do not populate the archive")
    args = ap.parse_args()

    raw_dir = Path(args.raw_dir)
    seasons = [int(s) for s in args.seasons.split(",") if s.strip()]
    fetched_at = datetime.now(timezone.utc)

    games_raw, _ = _get_raw(raw_dir, "games", None)
    schedule = load_schedule(games_raw)

    raw_files: dict[tuple[str, int], bytes] = {}
    for season in seasons:
        for name in SIGNALS:
            raw, _ = _get_raw(raw_dir, name, season)
            raw_files[(name, season)] = raw

    if not args.skip_archive:
        archive = ParticipationArchive(args.archive_dir)
        archive.store_raw_payload(games_raw)
        for season in seasons:
            bridge = build_pfr_gsis_bridge(raw_files[("weekly_rosters", season)], season)
            jobs = [
                ("injuries", collect_injuries),
                ("weekly_rosters", collect_rosters),
                ("depth_charts", collect_depth_charts),
                ("snap_counts", collect_snap_counts),
            ]
            for name, fn in jobs:
                url = URL_TEMPLATES[name].format(season=season)
                if name == "snap_counts":
                    receipt = fn(archive, schedule, season, raw_files[(name, season)],
                                 url, fetched_at, pfr_to_gsis=bridge)
                else:
                    receipt = fn(archive, schedule, season, raw_files[(name, season)],
                                 url, fetched_at)
                print(f"{season} {name}: rows={receipt['rows_in']} "
                      f"records={receipt['records_written']} "
                      f"rejections={receipt['rejections']}")

    coverage = compute_all(raw_files, games_raw)
    if args.coverage_json:
        out = Path(args.coverage_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(coverage, indent=2), encoding="utf-8")
        print(f"coverage written to {out}")
    gates = coverage["gates"]["primary_fitting_2019_2024"]
    print(json.dumps(gates, indent=2))


if __name__ == "__main__":
    main()
