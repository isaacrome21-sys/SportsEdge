#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from sportsedge.mlb_game_context_source import fetch_game_context
from sportsedge.mlb_source import fetch_schedule

CHICAGO_TZ = ZoneInfo("America/Chicago")


def main() -> int:
    now = datetime.now(timezone.utc)
    slate_date = now.astimezone(CHICAGO_TZ).date().isoformat()
    out = Path("artifacts/mlb-context") / slate_date
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "retrieved_at": now.isoformat(),
        "slate_date_ct": slate_date,
        "games": 0,
        "games_scheduled": 0,
        "weather_present": 0,
        "weather_absent": 0,
        "lineups_present": 0,
        "lineups_absent": 0,
        "umpires_present": 0,
        "umpires_absent": 0,
        "catchers_present": 0,
        "catchers_absent": 0,
        "failures": [],
    }
    try:
        schedule = fetch_schedule(slate_date, now=now)
    except Exception as exc:
        summary["status"] = "ERROR"
        summary["failures"].append({"stage": "SCHEDULE", "reason": f"{type(exc).__name__}:{exc}"})
        (out / "manifest.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 3

    summary["games_scheduled"] = len(schedule)
    for game in schedule:
        try:
            snap = fetch_game_context(game.game_pk, now=now)
            payload = {
                "game_id": snap.game_id,
                "retrieved_at": snap.retrieved_at,
                "source": snap.source,
                "source_states": snap.source_states,
                "weather": snap.weather,
                "umpire": snap.umpire,
                "lineups": list(snap.lineups),
                "catchers": list(snap.catchers),
            }
            (out / f"game_{snap.game_id}.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            summary["games"] += 1
            for key, present_key, absent_key in (
                ("weather_first_pitch_forecast", "weather_present", "weather_absent"),
                ("confirmed_lineup", "lineups_present", "lineups_absent"),
                ("plate_umpire", "umpires_present", "umpires_absent"),
                ("starting_catcher", "catchers_present", "catchers_absent"),
            ):
                summary[present_key if snap.source_states.get(key) == "PRESENT" else absent_key] += 1
        except Exception as exc:
            summary["failures"].append({"stage": "GAME_CONTEXT", "game_id": str(game.game_pk), "reason": f"{type(exc).__name__}:{exc}"})

    if not schedule:
        summary["status"] = "NO_GAMES"
    elif summary["games"] == summary["games_scheduled"] and not summary["failures"]:
        summary["status"] = "PASS"
    else:
        summary["status"] = "INCOMPLETE"
    (out / "manifest.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] in {"PASS", "NO_GAMES"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
