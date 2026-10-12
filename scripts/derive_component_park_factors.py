#!/usr/bin/env python3
"""Derive COMPONENT MLB park factors from Retrosheet play-by-play (free).

Method (Derek Carty / THE BAT pattern):
- Components computed SEPARATELY: 1B, 2B, 3B, HR, BB (incl HBP), K.
  NOT aggregate runs. Each component has its own park factor.
- Road-weight: for each team, component rate at HOME vs on the ROAD.
  Park factor = home_rate / road_rate (controls for team quality).
- Regress by noisiness: each component regressed toward 1.0 with a
  declared per-component constant (rarer events regress more).

Source: Retrosheet event files (free, retrosheet.org).
Files: data/retrosheet/{2022,2023,2024}eve.zip (unzipped).

Output: data/component_park_factors_2022_2024.json
Keyed by TEAM (2022-2024 home park). For 2025+, A's/Rays fail closed
(park changes) as with the aggregate table.

Research only. No betting authority.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path

# Declared regression constants in PLATE APPEARANCES of league average.
# Rarer/noisier events regress more (stabilization logic).
REGRESS_PA = {
    "1B": 6500,   # singles: common
    "2B": 8000,   # doubles
    "3B": 16000,  # triples: rare, heavy regression
    "HR": 6500,   # home runs
    "BB": 6500,   # walks (+HBP)
    "K": 4000,    # strikeouts: very common, least regression
}
MIN_HOME_PA = 8000  # ~1.2 seasons of home PA for stability


def classify_event(event: str) -> str | None:
    e = event.split("/")[0].split("+")[0]
    if re.fullmatch(r"K\d*", e):
        return "K"
    if e in ("W", "IW", "I", "HP"):
        return "BB"
    if re.fullmatch(r"S\d*", e):
        return "1B"
    if re.fullmatch(r"D\d*", e):
        return "2B"
    if re.fullmatch(r"T\d*", e):
        return "3B"
    if e == "HR" or re.fullmatch(r"HR\d*", e) or re.fullmatch(r"H\d+", e):
        return "HR"
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="2022,2023,2024")
    ap.add_argument("--data-dir", default="data/retrosheet")
    ap.add_argument("--out", default="data/component_park_factors_2022_2024.json")
    args = ap.parse_args(argv)
    seasons = [int(s) for s in args.seasons.split(",")]
    data_dir = Path(args.data_dir)

    # team -> comp -> [home_events, road_events]
    # team -> [home_pa, road_pa]
    comp_agg: dict[str, dict[str, list[int]]] = {}
    pa_agg: dict[str, list[int]] = {}
    # Map Retrosheet abbrev -> full name (for output readability).
    # We'll use abbrev as key and map at the end.
    n_games = 0
    for season in seasons:
        pattern = str(data_dir / f"{season}*.EV*")
        for filepath in sorted(glob.glob(pattern)):
            hometeam = None
            visteam = None
            with open(filepath, "r", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(",")
                    tag = parts[0]
                    if tag == "id":
                        n_games += 1
                        hometeam = visteam = None
                    elif tag == "info" and len(parts) >= 3:
                        if parts[1] == "hometeam":
                            hometeam = parts[2]
                        elif parts[1] == "visteam":
                            visteam = parts[2]
                    elif tag == "play" and len(parts) >= 7:
                        if not hometeam or not visteam:
                            continue
                        try:
                            home_batting = parts[2] == "1"
                            event = parts[6]
                        except IndexError:
                            continue
                        # Attribute to the BATTING team; home/road by context.
                        team = hometeam if home_batting else visteam
                        is_home = home_batting
                        pa = pa_agg.setdefault(team, [0, 0])
                        pa[0 if is_home else 1] += 1
                        comp = classify_event(event)
                        if comp:
                            d = comp_agg.setdefault(team, {})
                            c = d.setdefault(comp, [0, 0])
                            c[0 if is_home else 1] += 1
    print(f"parsed {n_games} games", flush=True)

    # Retrosheet abbrev -> full team name (2022-2024).
    ABBREV_TO_NAME = {
        "ANA": "Los Angeles Angels", "ARI": "Arizona Diamondbacks",
        "ATL": "Atlanta Braves", "BAL": "Baltimore Orioles",
        "BOS": "Boston Red Sox", "CHA": "Chicago White Sox",
        "CHN": "Chicago Cubs", "CIN": "Cincinnati Reds",
        "CLE": "Cleveland Guardians", "COL": "Colorado Rockies",
        "DET": "Detroit Tigers", "HOU": "Houston Astros",
        "KCA": "Kansas City Royals", "LAN": "Los Angeles Dodgers",
        "MIA": "Miami Marlins", "MIL": "Milwaukee Brewers",
        "MIN": "Minnesota Twins", "NYA": "New York Yankees",
        "NYN": "New York Mets", "OAK": "Oakland Athletics",
        "PHI": "Philadelphia Phillies", "PIT": "Pittsburgh Pirates",
        "SDN": "San Diego Padres", "SFN": "San Francisco Giants",
        "SEA": "Seattle Mariners", "SLN": "St. Louis Cardinals",
        "TBA": "Tampa Bay Rays", "TEX": "Texas Rangers",
        "TOR": "Toronto Blue Jays", "WAS": "Washington Nationals",
    }

    table: dict[str, dict] = {}
    for abbrev, (home_pa, road_pa) in sorted(pa_agg.items()):
        name = ABBREV_TO_NAME.get(abbrev, abbrev)
        if home_pa < MIN_HOME_PA:
            print(f"SKIP {abbrev}: only {home_pa} home PA", flush=True)
            continue
        comps = {}
        for comp in ("1B", "2B", "3B", "HR", "BB", "K"):
            h, r = comp_agg.get(abbrev, {}).get(comp, [0, 0])
            home_rate = h / home_pa if home_pa else 0
            road_rate = r / road_pa if road_pa else 0
            if road_rate <= 0 or home_rate <= 0:
                continue
            raw = home_rate / road_rate
            rg = REGRESS_PA[comp]
            pf = 1.0 + (raw - 1.0) * home_pa / (home_pa + rg)
            comps[comp] = {
                "pf": round(pf, 4),
                "raw": round(raw, 4),
                "home_pa": home_pa,
            }
        if comps:
            table[name] = comps

    payload = {
        "schema": "SPORTSEDGE_COMPONENT_PARK_FACTORS_V1",
        "source": "Retrosheet play-by-play event files (free, retrosheet.org)",
        "seasons": seasons,
        "method": ("Carty/THE BAT pattern: components computed separately; "
                   "road-weight (team home rate vs road rate); regressed by "
                   "noisiness with declared per-component PA constants"),
        "regress_pa": REGRESS_PA,
        "teams": table,
        "research_only": True,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out} with {len(table)} teams")
    # Print HR factors for sanity check
    print("\nHR park factors (top 5 / bottom 5):")
    hr = sorted(((t, c["HR"]["pf"]) for t, c in table.items()
                 if "HR" in c), key=lambda x: x[1])
    for t, pf in hr[:5] + hr[-5:]:
        print(f"  {t}: {pf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
