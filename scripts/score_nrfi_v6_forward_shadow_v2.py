#!/usr/bin/env python3
"""Correct MLB linescore settlement adapter for the cumulative NRFI V6 scorer."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.request import urlopen

import scripts.score_nrfi_v6_forward_shadow as scorer

SOURCE = "MLB_STATSAPI_LIVE_FEED_LINESCORE_V2"


def fetch_first_inning(game_id: str):
    url = f"https://statsapi.mlb.com/api/v1.1/game/{int(game_id)}/feed/live"
    try:
        with urlopen(url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    status = (((payload.get("gameData") or {}).get("status") or {}).get("abstractGameState"))
    if status != "Final":
        return None
    innings = (((payload.get("liveData") or {}).get("linescore") or {}).get("innings") or [])
    if not innings:
        return None
    first = innings[0] or {}
    if int(first.get("num") or 0) != 1:
        return None
    try:
        away = int((first.get("away") or {}).get("runs"))
        home = int((first.get("home") or {}).get("runs"))
    except (TypeError, ValueError):
        return None
    return {
        "game_id": str(game_id),
        "away_first_inning_runs": away,
        "home_first_inning_runs": home,
        "yrfi_outcome": int((away + home) > 0),
        "nrfi_outcome": int((away + home) == 0),
        "source": SOURCE,
        "settled_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def discard_legacy_bad_settlements() -> None:
    out_root = Path(os.getenv("SPORTSEDGE_NRFI_V6_SCORE_OUT", "artifacts/forward-shadow-scored"))
    path = out_root / "nrfi_v6_settlements.json"
    if not path.exists():
        return
    try:
        rows = json.loads(path.read_text())
    except Exception:
        path.unlink(missing_ok=True)
        return
    keep = [row for row in rows if isinstance(row, dict) and row.get("source") == SOURCE]
    path.write_text(json.dumps(keep, sort_keys=True, separators=(",", ":")) + "\n")


def main() -> int:
    discard_legacy_bad_settlements()
    scorer.fetch_first_inning = fetch_first_inning
    return scorer.main()


if __name__ == "__main__":
    raise SystemExit(main())
