#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from sportsedge.mlb_source import fetch_schedule
from sportsedge.pregame_archive import update_pregame_archive

CT = ZoneInfo("America/Chicago")


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def main() -> int:
    now = datetime.now(timezone.utc)
    date_ct = now.astimezone(CT).date().isoformat()
    root = Path(".cache/sportsedge/pregame-archive")
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{date_ct}.json"
    payload = update_pregame_archive(
        schedule=fetch_schedule(date_ct, now=now),
        now=now,
        prior=_load(path),
        card_payload=_load(Path("artifacts/live_mlb_card.json")),
        game_odds_payload=_load(Path("artifacts/live_game_odds.json")),
    )
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"slate_date_ct": date_ct, "archived_games": len(payload["games"])}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
