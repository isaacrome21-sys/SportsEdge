#!/usr/bin/env python3
"""Fetch fresh DraftKings ML/RL/totals and bind them to today's MLB schedule."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from sportsedge.game_odds_source import fetch_mlb_game_quotes
from sportsedge.mlb_source import fetch_schedule
from sportsedge.odds_keyring import fetch_with_key_failover

CT = ZoneInfo("America/Chicago")


def main() -> int:
    now = datetime.now(timezone.utc)
    slate_date = now.astimezone(CT).date().isoformat()
    keys = tuple(x for x in (
        os.environ.get("SPORTSEDGE_ODDS_API_KEY", "").strip(),
        os.environ.get("SPORTSEDGE_ODDS_API_KEY_2", "").strip(),
        os.environ.get("SPORTSEDGE_ODDS_API_KEY_3", "").strip(),
        os.environ.get("SPORTSEDGE_ODDS_API_KEY_4", "").strip(),
    ) if x)
    books = tuple(x.strip() for x in os.environ.get("SPORTSEDGE_ODDS_BOOKMAKERS", "draftkings").split(",") if x.strip())
    out = Path(os.environ.get("SPORTSEDGE_GAME_ODDS_OUTPUT", "artifacts/live_game_odds.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    if not keys:
        payload = {"generated_at_utc": now.isoformat(), "slate_date_ct": slate_date, "quotes": [], "failures": [{"reason": "ODDS_API_KEY_MISSING"}]}
        out.write_text(json.dumps(payload, indent=2, default=str) + "\n")
        return 2
    schedule = fetch_schedule(slate_date, now=now)
    result = fetch_with_key_failover(keys, lambda key: fetch_mlb_game_quotes(api_key=key, schedule=schedule, bookmakers=books))
    snap = result.value
    payload = {
        "generated_at_utc": now.isoformat(),
        "slate_date_ct": slate_date,
        "quotes": list(snap.quotes),
        "failures": [
            *[{"stage": "KEY_FAILOVER", "key_slot": x.key_slot, "reason": x.reason} for x in result.failures],
            *list(snap.failures),
        ],
    }
    out.write_text(json.dumps(payload, indent=2, default=str, sort_keys=True) + "\n")
    print(json.dumps({"slate_date_ct": slate_date, "quotes": len(snap.quotes), "failures": len(payload["failures"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
