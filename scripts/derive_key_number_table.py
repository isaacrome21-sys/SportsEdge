#!/usr/bin/env python3
"""Derive empirical final-margin frequencies for NFL/CFB from free verified data.

Source: ESPN public scoreboard API (free, public, no key):
    https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
    https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard
Only completed regular-season + postseason games; final margins recorded.

Output: data/key_number_margins.json with P(home_margin == k) for
k = 0..40 per sport, plus the blended push-probability table used by
sportsedge/free_factors.py. Python literal printed for baking in.

Research only. No betting authority.
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

SCOREBOARD = {
    "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
    "cfb": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
}
MAX_MARGIN = 40


def _get(url: str) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": "SportsEdge-free-research/1.0",
                      "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    if not isinstance(data, dict):
        raise ValueError("NOT_JSON_OBJECT:" + url)
    return data


# ESPN's scoreboard honors ?dates=YYYYMMDD for history; season/week params
# return the current season only. Iterate game-days per season instead.
from datetime import date, timedelta

FIRST_THURSDAY = {  # season-opening Thursday kickoff per season
    "nfl": {2020: date(2020, 9, 10), 2021: date(2021, 9, 9),
            2022: date(2022, 9, 8), 2023: date(2023, 9, 7),
            2024: date(2024, 9, 5), 2025: date(2025, 9, 4)},
    "cfb": {2021: date(2021, 8, 28), 2022: date(2022, 8, 27),
            2023: date(2023, 8, 26), 2024: date(2024, 8, 24)},
}
# NFL: Thu/Sun/Mon (+Sat weeks 15+). CFB: Sat (+Fri/Thu).
NFL_WEEKS, CFB_WEEKS = 22, 16


def season_game_days(sport: str, season: int):
    start = FIRST_THURSDAY[sport][season]
    days = []
    n_weeks = NFL_WEEKS if sport == "nfl" else CFB_WEEKS
    for w in range(n_weeks):
        thu = start + timedelta(days=7 * w)
        if sport == "nfl":
            days += [thu, thu + timedelta(days=3), thu + timedelta(days=4)]
            if w >= 14:  # late-season Saturday games
                days.append(thu + timedelta(days=2))
        else:
            sat = thu + timedelta(days=2)
            days += [sat - timedelta(days=1), sat, thu]
    return days


def season_margins(sport: str, season: int) -> list[int]:
    margins = []
    seen: set[str] = set()
    for day in season_game_days(sport, season):
        url = SCOREBOARD[sport] + "?" + urlencode(
            {"dates": day.strftime("%Y%m%d")})
        try:
            data = _get(url)
        except Exception:
            continue
        for ev in data.get("events") or []:
            eid = str(ev.get("id") or "")
            if not eid or eid in seen:
                continue
            stype = ((ev.get("status") or {}).get("type")) or {}
            if stype.get("completed") is not True:
                continue
            seen.add(eid)
            comp = (ev.get("competitions") or [{}])[0]
            comps = comp.get("competitors") or []
            home = next((c for c in comps if c.get("homeAway") == "home"), None)
            away = next((c for c in comps if c.get("homeAway") == "away"), None)
            if home is None or away is None:
                continue
            try:
                hs = int(home.get("score"))
                aws = int(away.get("score"))
            except (TypeError, ValueError):
                continue
            margins.append(hs - aws)
    return margins


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nfl-seasons", default="2020,2021,2022,2023,2024")
    ap.add_argument("--cfb-seasons", default="2021,2022,2023,2024")
    ap.add_argument("--out", default="data/key_number_margins.json")
    args = ap.parse_args(argv)

    table: dict[str, dict] = {}
    for sport, seasons in (("nfl", args.nfl_seasons), ("cfb", args.cfb_seasons)):
        margins: list[int] = []
        for season in [int(s) for s in seasons.split(",")]:
            got = season_margins(sport, season)
            print(f"{sport} {season}: {len(got)} completed games")
            margins.extend(got)
        n = len(margins)
        freq = {str(k): 0 for k in range(MAX_MARGIN + 1)}
        over = 0
        for m in margins:
            a = abs(m)
            if a <= MAX_MARGIN:
                freq[str(a)] += 1
            else:
                over += 1
        table[sport] = {
            "seasons": seasons,
            "n_games": n,
            "p_abs_margin_eq_k": {k: round(v / n, 6) for k, v in freq.items()},
            "p_abs_margin_gt_40": round(over / n, 6),
        }

    payload = {
        "schema": "SPORTSEDGE_KEY_NUMBER_MARGINS_V1",
        "source": "ESPN public scoreboard API (free, public, no key)",
        "source_urls": list(SCOREBOARD.values()),
        "note": ("Empirical P(|home margin| == k). The production push model "
                 "blends this with the normal-model push estimate; see "
                 "sportsedge/free_factors.py key_number_push_probability."),
        "sports": table,
        "research_only": True,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out}")
    for sport in ("nfl", "cfb"):
        print(f"# {sport} top key numbers:")
        freqs = table[sport]["p_abs_margin_eq_k"]
        top = sorted(freqs.items(), key=lambda kv: -kv[1])[:8]
        print("   " + ", ".join(f"{k}:{v:.4f}" for k, v in top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
