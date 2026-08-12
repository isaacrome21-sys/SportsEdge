#!/usr/bin/env python3
"""Build full-day MLB game/market accounting without silently dropping started games."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from sportsedge.full_slate_accounting import build_full_slate_accounting
from sportsedge.mlb_source import fetch_schedule

CT = ZoneInfo("America/Chicago")


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def main() -> int:
    now = datetime.now(timezone.utc)
    slate_date = now.astimezone(CT).date().isoformat()
    schedule = fetch_schedule(slate_date, now=now)
    payload = build_full_slate_accounting(
        schedule=schedule,
        now=now,
        card_payload=_load(Path("artifacts/live_mlb_card.json")),
        game_odds_payload=_load(Path("artifacts/live_game_odds.json")),
    )
    payload["slate_date_ct"] = slate_date
    out = Path("artifacts/full_slate_accounting.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"slate_date_ct": slate_date, "scheduled_games": payload["scheduled_games"], "complete_game_accounting": payload["complete_game_accounting"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
