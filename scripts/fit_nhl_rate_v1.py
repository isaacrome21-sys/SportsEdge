#!/usr/bin/env python3
"""Fit NHLRateParameters v1 from official api-web.nhle.com boxscores.

Fit window is 2024-25 REG only. Does not score 2025-26.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from sportsedge.sports.nhl.official_rate_standin import feature_row, prior_team_rates
from sportsedge.sports.nhl.training import NHLRateTrainingRow, fit_rate_parameters

BASE = "https://api-web.nhle.com"
UA = {"User-Agent": "SportsEdge-NHL-rate-v1/1.0", "Accept": "application/json"}
FIT_START = date(2024, 10, 8)
FIT_END = date(2025, 4, 18)


def _get(path: str) -> dict:
    with urlopen(Request(BASE + path, headers=UA), timeout=30) as response:
        return json.loads(response.read().decode())


def iter_schedule(start: date, end: date) -> list[dict]:
    cursor = start
    seen = set()
    games = []
    while cursor <= end:
        payload = _get(f"/v1/schedule/{cursor.isoformat()}")
        for day in payload.get("gameWeek") or []:
            for game in day.get("games") or []:
                gid = str(game.get("id") or "")
                if not gid or gid in seen:
                    continue
                if str(game.get("gameType")) not in {"2", "REG", "regular"} and game.get("gameType") != 2:
                    # api uses numeric 2 for REG
                    if game.get("gameType") != 2:
                        continue
                if str(game.get("gameState") or "") not in {"OFF", "FINAL"} and game.get("gameScheduleState") == "CNCL":
                    continue
                start_utc = game.get("startTimeUTC") or ""
                if not start_utc:
                    continue
                day_date = date.fromisoformat(str(day.get("date") or cursor.isoformat())[:10])
                if day_date < start or day_date > end:
                    continue
                seen.add(gid)
                home = game.get("homeTeam") or {}
                away = game.get("awayTeam") or {}
                games.append({
                    "id": gid,
                    "start_utc": start_utc,
                    "home_id": str(home.get("id") or home.get("abbrev") or ""),
                    "away_id": str(away.get("id") or away.get("abbrev") or ""),
                    "home_gf": home.get("score"),
                    "away_gf": away.get("score"),
                    "state": game.get("gameState"),
                    "game_type": game.get("gameType"),
                })
        nxt = payload.get("nextStartDate")
        if not nxt:
            break
        nxt_date = date.fromisoformat(str(nxt)[:10])
        if nxt_date <= cursor:
            break
        cursor = nxt_date
    return games


def boxscore_sog(game_id: str) -> tuple[int, int] | None:
    try:
        payload = _get(f"/v1/gamecenter/{game_id}/boxscore")
    except Exception:
        return None
    home = (payload.get("homeTeam") or {})
    away = (payload.get("awayTeam") or {})
    try:
        return int(home.get("sog") or home.get("shotsOnGoal") or 0), int(away.get("sog") or away.get("shotsOnGoal") or 0)
    except (TypeError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--schedule-only", action="store_true")
    ap.add_argument("--output", default="artifacts/nhl/nhl_rate_v1_fit_2024_25.json")
    args = ap.parse_args()
    schedule = [g for g in iter_schedule(FIT_START, FIT_END) if g["home_gf"] is not None and g["away_gf"] is not None]
    if args.schedule_only:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps({"games": len(schedule), "sample": schedule[:3]}, indent=2) + "\n")
        print(json.dumps({"games": len(schedule)}))
        return 0
    rows = []
    completed = []
    for game in schedule:
        sog = boxscore_sog(str(game["id"]))
        if sog is None:
            continue
        completed.append({
            "id": game["id"],
            "start_utc": game["start_utc"],
            "home_id": game["home_id"],
            "away_id": game["away_id"],
            "home_gf": int(game["home_gf"]),
            "away_gf": int(game["away_gf"]),
            "home_sog": sog[0],
            "away_sog": sog[1],
            "minutes": 60.0,
        })
    for game in completed:
        asof = datetime.fromisoformat(str(game["start_utc"]).replace("Z", "+00:00")).astimezone(timezone.utc)
        home = prior_team_rates(completed, team_id=str(game["home_id"]), asof=asof)
        away = prior_team_rates(completed, team_id=str(game["away_id"]), asof=asof)
        if home is None or away is None:
            continue
        rows.append(NHLRateTrainingRow(str(game["id"]) + ":H", game["start_utc"], feature_row(home, away, home_side=True), int(game["home_gf"])))
        rows.append(NHLRateTrainingRow(str(game["id"]) + ":A", game["start_utc"], feature_row(home, away, home_side=False), int(game["away_gf"])))
    params = fit_rate_parameters(rows, version="nhl_rate_v1_official_boxscore_2024_25")
    payload = {
        "version": params.version,
        "fit_window": {"start": FIT_START.isoformat(), "end": FIT_END.isoformat()},
        "validate_window_reserved": {"start": "2025-10-07", "end": "2026-04-18"},
        "n_schedule": len(schedule),
        "n_boxscores": len(completed),
        "n_training_rows": len(rows),
        "parameters": params.__dict__,
        "standin": "GF/60 and GA/60 occupy offense_xg and opponent_xga slots. GSAx/travel/lineup are 0.",
        "status": "RESEARCH_FIT_ONLY_NOT_VALIDATED",
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"n_training_rows": len(rows), "version": params.version}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
