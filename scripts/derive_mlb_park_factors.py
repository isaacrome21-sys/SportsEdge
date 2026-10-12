#!/usr/bin/env python3
"""Derive MLB runs park factors from free verified MLB StatsAPI data.

Source: MLB StatsAPI official schedule endpoint (free, public, no key).
NOTE (2026-10-11): the schedule endpoint IGNORES the `team=` query
parameter (verified); this script therefore fetches full-season schedules
and groups games by team in Python. Do not reintroduce `team=`.

Formula (documented, standard team-based park factor):
    For each team T over the covered seasons:
        home_rpg = (runs scored + runs allowed at home) / home games
        road_rpg = (runs scored + runs allowed on road) / road games
        raw_pf[T] = home_rpg / road_rpg
    Regress toward 1.0 (neutral):
        pf[T] = 1 + (raw_pf[T] - 1) * n_home / (n_home + REGRESS_GAMES)
    where REGRESS_GAMES = 162 (one full season of home games).

This is the park the team played its home games in during the covered
seasons (team-keyed, so a franchise move is handled by re-derivation).

Output: data/park_factors_<seasons>.json with the table + provenance, and
a Python literal printed for baking into sportsedge/free_factors.py.

Research only. No betting authority.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

STATSAPI = "https://statsapi.mlb.com/api/v1"
REGRESS_GAMES = 162  # regression constant: one season of home games
MIN_HOME_GAMES = 200  # require ~2.5 seasons of home games for stability


def _get(url: str) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": "SportsEdge-free-research/1.0",
                      "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    if not isinstance(data, dict):
        raise ValueError("NOT_JSON_OBJECT:" + url)
    return data


def season_games(season: int) -> list[dict]:
    # Full-season schedule; group by team locally (team= is ignored by API).
    url = (f"{STATSAPI}/schedule?sportId=1&startDate={season}-01-01"
           f"&endDate={season}-12-31")
    data = _get(url)
    games = []
    for day in data.get("dates") or []:
        games.extend(day.get("games") or [])
    return games


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="2022,2023,2024")
    ap.add_argument("--out", default="data/park_factors.json")
    args = ap.parse_args(argv)
    seasons = [int(s) for s in args.seasons.split(",")]

    # team -> [home_rs, home_ra, home_g, road_rs, road_ra, road_g]
    agg: dict[str, list[float]] = {}
    for season in seasons:
        games = season_games(season)
        print(f"season {season}: {len(games)} scheduled games", file=sys.stderr)
        for g in games:
            status = str((g.get("status") or {}).get("detailedState") or "")
            if status != "Final":
                continue
            teams = g.get("teams") or {}
            home = teams.get("home") or {}
            away = teams.get("away") or {}
            try:
                hs = int(home.get("score"))
                aws = int(away.get("score"))
            except (TypeError, ValueError):
                continue
            hn = str(((home.get("team") or {}).get("name")) or "").strip()
            an = str(((away.get("team") or {}).get("name")) or "").strip()
            if not hn or not an:
                continue
            h = agg.setdefault(hn, [0.0] * 6)
            a = agg.setdefault(an, [0.0] * 6)
            h[0] += hs
            h[1] += aws
            h[2] += 1
            a[3] += aws
            a[4] += hs
            a[5] += 1

    table: dict[str, dict] = {}
    for name, (hrs, hra, hg, rrs, rra, rg) in sorted(agg.items()):
        if hg < MIN_HOME_GAMES or rg < MIN_HOME_GAMES:
            print(f"SKIP {name}: only {hg:.0f}H/{rg:.0f}R games", file=sys.stderr)
            continue
        home_rpg = (hrs + hra) / hg
        road_rpg = (rrs + rra) / rg
        raw = home_rpg / road_rpg if road_rpg > 0 else 1.0
        pf = 1.0 + (raw - 1.0) * hg / (hg + REGRESS_GAMES)
        table[name] = {
            "park_factor_runs": round(pf, 4),
            "raw_home_road_ratio": round(raw, 4),
            "home_games": int(hg),
            "home_rpg": round(home_rpg, 3),
            "road_rpg": round(road_rpg, 3),
        }

    payload = {
        "schema": "SPORTSEDGE_PARK_FACTORS_V1",
        "source": "MLB StatsAPI official schedule (free, public, no key)",
        "source_urls": [f"{STATSAPI}/schedule?sportId=1&season=<s>"],
        "seasons": seasons,
        "formula": ("pf = 1 + (home_rpg/road_rpg - 1) * home_games/(home_games+162); "
                    "home_rpg and road_rpg count runs scored AND allowed; "
                    "schedule team= param is ignored by the API so games are "
                    "grouped by team locally"),
        "regress_games": REGRESS_GAMES,
        "teams": table,
        "research_only": True,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out} with {len(table)} teams")
    print("PARK_FACTORS = {")
    for name in sorted(table):
        print(f"    {name!r}: {table[name]['park_factor_runs']},")
    print("}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
