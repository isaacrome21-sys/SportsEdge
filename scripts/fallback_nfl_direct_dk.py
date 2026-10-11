#!/usr/bin/env python3
"""Free NFL DK transport fallback when the configured Odds API cannot price games.

This transport is independent of the paid API and remains strictly limited to
intake-stamped two-sided game spread/total offers. The direct DK endpoint is
unofficial: connection failure is a visible UNAVAILABLE, never a fabricated
price or probability.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
from typing import Callable,Any
from zoneinfo import ZoneInfo

from scripts.collect_auto_dk_four_sports import good_price,iso_time
from sportsedge.nfl_direct_capture_source import (
    SOURCE_CLASS, DirectCaptureError, acquire_board,game_rows_direct
)
from sportsedge.nfl_team_aliases import resolve_team,NflTeamAliasError

CENTRAL=ZoneInfo("America/Chicago")
MAX_AGE_SECONDS=600
HORIZON_DAYS=7


def convert(transport:dict, rows:list,now:datetime):
    if transport.get("source_class")!=SOURCE_CLASS:
        raise ValueError("DK_DIRECT_SOURCE_CLASS_MISMATCH")
    received=iso_time(transport.get("observed_at_utc"))
    if received is None or not 0<=(now-received).total_seconds()<=MAX_AGE_SECONDS:
        raise ValueError("DK_DIRECT_INTAKE_STAMP_STALE_OR_INVALID")
    if not transport.get("raw_sha256") or not transport.get("source_uri"):
        raise ValueError("DK_DIRECT_RAW_PROVENANCE_REQUIRED")
    games=[]; seen=set()
    for r in rows:
        if not isinstance(r,dict) or r.get("book")!="draftkings":
            continue
        start=iso_time(r.get("commence_time"))
        if start is None or not now<start<=now+timedelta(days=HORIZON_DAYS):
            continue
        try:
            away,home=resolve_team(r["away_team"]),resolve_team(r["home_team"])
        except (KeyError,NflTeamAliasError):
            continue
        if away==home or not str(r.get("event_id") or ""):
            continue
        identity=(str(r["event_id"]),away,home,start.isoformat())
        if identity in seen:
            raise ValueError("DK_DIRECT_DUPLICATE_GAME_IDENTITY")
        seen.add(identity)
        spread,total=r.get("spread") or {},r.get("total") or {}
        observed=received.isoformat()
        stamp={"observed_at":observed,"timestamp_source":"INTAKE_STAMPED",
               "book_last_update":None,"provider":"DRAFTKINGS_DIRECT_WEB_V1"}
        markets={}
        # Preserve whichever two-sided market was actually captured. A
        # one-sided spread must never suppress an independently valid total,
        # and vice versa; no missing opposing price may be manufactured.
        if spread.get("status")=="OK":
            try:
                ap,hp=float(spread["away_point"]),float(spread["home_point"])
                a,b=good_price(spread.get("away_price")),good_price(spread.get("home_price"))
                if (-100<ap<100 and abs(ap+hp)<1e-9
                        and a is not None and b is not None):
                    markets["spreads"]={"line":ap,"away":a,"home":b,**stamp}
            except (ValueError,TypeError,KeyError,OverflowError):
                pass
        if total.get("status")=="OK":
            try:
                t=float(total["point"])
                o,u=good_price(total.get("over_price")),good_price(total.get("under_price"))
                if 0<t<150 and o is not None and u is not None:
                    markets["totals"]={"line":t,"over":o,"under":u,**stamp}
            except (ValueError,TypeError,KeyError,OverflowError):
                pass
        if not markets:
            continue
        games.append({
            "provider_event_id":str(r["event_id"]), "away":r["away_team"],
            "home":r["home_team"],"commence_time":start.isoformat(),
            "slate_ct":start.astimezone(CENTRAL).date().isoformat(),
            "markets":markets,
            "reference":{},"peer_books":[],"estimate_p":None
        })
    games.sort(key=lambda x:(x["commence_time"],x["provider_event_id"]))
    return games


def fallback(path:Path,now:datetime,*,capture:Callable=acquire_board,
             rows_from:Callable=game_rows_direct):
    try: previous=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError,TypeError): previous={"sport":"NFL","games":[],"status":"UNAVAILABLE"}
    if previous.get("status")=="READY" and previous.get("games"):
        return {"status":"ODDS_API_ALREADY_READY","games":len(previous["games"])}
    try:
        transport=capture()
        rows=rows_from(transport,week_of=lambda _:None)
        games=convert(transport,rows,now)
        if not games:
            return {"status":"NO_ADMISSIBLE_DIRECT_DK_GAMES","games":0}
    except (DirectCaptureError,ValueError,TypeError,OSError,KeyError) as error:
        return {"status":"DIRECT_DK_UNAVAILABLE","reason":type(error).__name__,"games":0}
    record={
        "sport":"NFL","status":"READY","source":"DRAFTKINGS_DIRECT_WEB_V1",
        "reason":None,"captured_at_utc":now.isoformat(),
        "book_quote_timestamp_source":"INTAKE_STAMPED",
        "source_uri":transport["source_uri"],"raw_sha256":transport["raw_sha256"],
        "requested_markets":["spreads","totals"],"cost_budget_credits":0,
        "games":games,"estimate_p":None
    }
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(record,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return {"status":"DIRECT_DK_INTAKE_STAMPED","games":len(games),
            "book_quote_timestamp":"MISSING"}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--odds-dir",type=Path,default=Path("artifacts/auto_dk"))
    args=ap.parse_args()
    outcome=fallback(args.odds_dir/"nfl_odds.json",datetime.now(timezone.utc))
    if outcome["status"]=="DIRECT_DK_INTAKE_STAMPED":
        with (args.odds_dir/"summary.md").open("a",encoding="utf-8") as file:
            file.write("\nNFL free direct fallback: "+str(outcome["games"])+
                " games, two-sided DK spreads/totals, timestamp INTAKE_STAMPED (not bookmaker last-update).\n")
    print(json.dumps(outcome,sort_keys=True))


if __name__=="__main__":
    main()
