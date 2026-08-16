#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from sportsedge.game_odds_source import fetch_mlb_game_quotes
from sportsedge.mlb_source import fetch_schedule

CT = ZoneInfo("America/Chicago")


def _keys():
    values=[]
    for name in ("SPORTSEDGE_ODDS_API_KEY","SPORTSEDGE_ODDS_API_KEY_2","SPORTSEDGE_ODDS_API_KEY_3","SPORTSEDGE_ODDS_API_KEY_4"):
        value=os.environ.get(name,"").strip()
        if value and value not in values:
            values.append(value)
    return values


def main() -> int:
    now=datetime.now(timezone.utc)
    slate=now.astimezone(CT).date().isoformat()
    books=tuple(x.strip() for x in os.environ.get("SPORTSEDGE_ODDS_BOOKMAKERS","draftkings").split(",") if x.strip())
    out=Path("artifacts/live_game_odds.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    schedule=fetch_schedule(slate)
    attempts=[]
    for slot,key in enumerate(_keys(),start=1):
        try:
            snap=fetch_mlb_game_quotes(api_key=key,schedule=schedule,bookmakers=books)
            payload={"generated_at_utc":now.isoformat(),"slate_date_ct":slate,"key_slot":slot,"quotes":list(snap.quotes),"failures":list(snap.failures)}
            out.write_text(json.dumps(payload,indent=2,default=str)+"\n")
            print(json.dumps({"key_slot":slot,"quote_count":len(snap.quotes),"failure_count":len(snap.failures)}))
            if snap.quotes:
                return 0
            attempts.append({"key_slot":slot,"reason":"NO_QUOTES"})
        except Exception as exc:
            attempts.append({"key_slot":slot,"reason":f"{type(exc).__name__}:{exc}"})
    payload={"generated_at_utc":now.isoformat(),"slate_date_ct":slate,"quotes":[],"failures":[{"reason":"FEATURED_ODDS_ALL_KEYS_FAILED","attempts":attempts}]}
    out.write_text(json.dumps(payload,indent=2)+"\n")
    print(json.dumps(payload))
    return 2

if __name__=="__main__":
    raise SystemExit(main())
