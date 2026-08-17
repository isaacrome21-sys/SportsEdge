#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from sportsedge.mlb_game_context_source import fetch_game_context
from sportsedge.mlb_source import fetch_schedule


def main() -> int:
    now = datetime.now(timezone.utc)
    slate_date = now.date().isoformat()
    schedule = fetch_schedule(slate_date, now=now)
    out = Path("artifacts/mlb-context") / slate_date
    out.mkdir(parents=True, exist_ok=True)

    summary = {"retrieved_at": now.isoformat(), "games": 0, "weather": 0, "lineups": 0, "umpires": 0, "catchers": 0, "failures": []}
    for game in schedule:
        try:
            snap = fetch_game_context(game.game_pk, now=now)
            payload = {
                "game_id": snap.game_id,
                "retrieved_at": snap.retrieved_at,
                "source": snap.source,
                "weather": snap.weather,
                "umpire": snap.umpire,
                "lineups": list(snap.lineups),
                "catchers": list(snap.catchers),
            }
            (out / f"game_{snap.game_id}.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            summary["games"] += 1
            summary["weather"] += int(bool(snap.weather))
            summary["lineups"] += len(snap.lineups)
            summary["umpires"] += int(bool(snap.umpire.get("home_plate_umpire_id")))
            summary["catchers"] += len(snap.catchers)
        except Exception as exc:
            summary["failures"].append({"game_id": str(game.game_pk), "reason": f"{type(exc).__name__}:{exc}"})

    summary["status"] = "PASS" if summary["games"] > 0 else "INCOMPLETE"
    (out / "manifest.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["games"] > 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
