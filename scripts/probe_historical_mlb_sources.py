#!/usr/bin/env python3
"""One-off probe of official MLB endpoints needed for reproducible market rebuilds."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "https://statsapi.mlb.com"


def get(path: str, params: dict) -> dict:
    url = f"{BASE}{path}?{urlencode(params)}"
    with urlopen(Request(url, headers={"Accept":"application/json"}), timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def first_game(schedule: dict) -> dict:
    for d in schedule.get("dates") or []:
        for g in d.get("games") or []:
            return g
    return {}


def main() -> int:
    out: dict = {}
    schedule = get("/api/v1/schedule", {
        "sportId": 1,
        "startDate": "2024-04-01",
        "endDate": "2024-04-03",
        "hydrate": "linescore,probablePitcher,team",
    })
    game = first_game(schedule)
    out["schedule"] = {
        "totalGames": schedule.get("totalGames"),
        "date_count": len(schedule.get("dates") or []),
        "game_keys": sorted(game.keys()),
        "game_sample": game,
    }
    stats = get("/api/v1/stats", {
        "stats": "gameLog",
        "group": "pitching",
        "season": 2024,
        "sportIds": 1,
        "limit": 5,
    })
    out["pitching_game_log"] = stats
    players = get("/api/v1/sports/1/players", {"season": 2024})
    out["players"] = {
        "count": len(players.get("people") or []),
        "sample": (players.get("people") or [])[:3],
    }
    path = Path("artifacts/historical_mlb_source_probe.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "schedule_games": out["schedule"]["totalGames"],
        "pitching_stats_blocks": len(stats.get("stats") or []),
        "players": out["players"]["count"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
