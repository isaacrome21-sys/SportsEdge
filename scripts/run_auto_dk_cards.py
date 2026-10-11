#!/usr/bin/env python3
"""Price captured automatic DK odds using existing NFL/CFB/MLB engines.

Never fetch odds here: only consume the credit-guarded artifact. All other
sources are free public features and can fail without manufacturing model p.
NBA remains capture-only. Each priced sport emits JSON and optionally PNG.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.collect_auto_dk_four_sports import cfb_compact, mlb_line_text, nfl_tickets

CT=ZoneInfo("America/Chicago")
ROOT=Path(__file__).resolve().parents[1]


def call(command, *, timeout=180, env=None):
    try:
        p=subprocess.run([sys.executable,*map(str,command)],cwd=ROOT,
                         capture_output=True,text=True,timeout=timeout,env=env)
    except (OSError,subprocess.TimeoutExpired) as exc:
        return False, type(exc).__name__
    return p.returncode==0,(p.stderr or p.stdout)[-2500:]


def image_card(card, sport, path):
    if not (ROOT/"scripts/render_sportsedge_png.py").is_file():
        return "PNG_RENDERER_NOT_MERGED"
    ok,details=call(["scripts/render_sportsedge_png.py","--card",card,
                      "--sport",sport,"--output",path],timeout=40)
    return "READY" if ok else "PNG_UNAVAILABLE:"+details[:120]


def week_candidate(start: str):
    """Only 2026 calendar heuristic; CFB runtime independently verifies schedule."""
    dt=datetime.fromisoformat(start.replace("Z","+00:00")).astimezone(CT)
    date=dt.date()
    # Friday games belong to the Saturday competition week.
    if date.weekday()==4:
        date+=timedelta(days=1)
    year=date.year
    if year != 2026:
        return None
    start_week_1=datetime(2026,9,5).date()
    week=max(1,1+(date-start_week_1).days//7)
    return (2026,min(16,week))


def run_nfl(raw, out, now):
    cards=[]
    days=nfl_tickets(raw.get("games") or [],now)
    if not days:
        return {"status":"NO_DK_GAMES","cards":[]}
    history=out/"nflverse_history.json"
    ok,detail=call(["scripts/fetch_nflverse_games.py","--output",history],timeout=105)
    for day,ticket in days.items():
        intake=out/("nfl_"+day+"_ticket.json")
        intake.write_text(json.dumps(ticket,indent=2)+"\n")
        card=out/("nfl_"+day+"_card.json")
        args=["scripts/run_nfl_lines_card.py","--input",intake,"--output",card]
        if ok and history.is_file():
            args+=["--history",history]
        success,message=call(args,timeout=100)
        if not success:
            cards.append({"date":day,"state":"NO_MODEL","reason":message[:250]})
            continue
        md_dir=out/("nfl_"+day+"_render")
        markdown,reason=call(["scripts/render_nfl_myspari_card.py",
               "--engine-output",card,"--snapshot",intake,"--pre-context",
               "--out-dir",md_dir],timeout=60)
        cards.append({"date":day,"state":"READY","json":str(card),
                      "md":str(md_dir/"card.md") if markdown else None,
                      "png":image_card(card,"NFL",out/("nfl_"+day+".png"))})
    return {"status":"READY" if any(x["state"]=="READY" for x in cards) else "MODEL_UNAVAILABLE",
            "history":"NFLVERSE" if ok else "MISSING",
            "cards":cards}


def run_cfb(raw, out, now):
    by_week=defaultdict(list)
    for game in raw.get("games") or []:
        key=week_candidate(game["commence_time"])
        if key is not None:
            by_week[key].append(game)
    if not by_week:
        return {"status":"NO_DK_GAMES","cards":[]}
    out_cards=[]
    for (season,week),games in sorted(by_week.items()):
        board=cfb_compact(games)
        card=out/f"cfb_{season}_w{week}_card.json"
        cmd=["scripts/run_cfb_sdv_card_v2.py","--board-json",json.dumps(board),
             "--season",season,"--week",week,"--asof",now.isoformat(),
             "--output",card]
        env=os.environ.copy()
        env["CFB_SHARP_FETCH"]="0" # No second charged request; peers are included.
        env["CFB_SDV_MAX_RETRY_SLEEP_SECONDS"]="10"
        if (out/"cfb_public").is_dir():
            cmd+=["--sdv-live-dir",out/"cfb_public"]
        success,reason=call(cmd,timeout=300,env=env)
        if success:
            out_cards.append({"season":season,"week":week,"state":"READY",
                              "json":str(card),"png":image_card(card,"CFB",out/f"cfb_w{week}.png")})
        else:
            out_cards.append({"season":season,"week":week,"state":"MODEL_UNAVAILABLE",
                              "reason":reason[:300]})
    return {"status":"READY" if any(x["state"]=="READY" for x in out_cards) else "MODEL_UNAVAILABLE",
            "cards":out_cards}


def mlb_auto_snapshot(games,now,*,fetch_schedule=None,build_bound_input=None):
    """Bind API-fed quotes to verified MLB starts, preserving source timestamps."""
    if fetch_schedule is None:
        from sportsedge.mlb_source import fetch_schedule as f
        fetch_schedule=f
    if build_bound_input is None:
        from sportsedge.mlb_resolve import build_bound_input as b
        build_bound_input=b
    from dataclasses import asdict
    from sportsedge.mlb_source import parse_game_start
    date=now.astimezone(CT).date()
    today=[g for g in games if g["slate_ct"]==date.isoformat()]
    if not today:
        return None
    schedule=list(fetch_schedule(date.isoformat()))+list(fetch_schedule((date+timedelta(days=1)).isoformat()))
    source_lines=mlb_line_text(today)
    snapshot=build_bound_input(source_lines,observed_at=now.isoformat(),schedule=schedule)
    # All lines were pulled from DK through the provider, not manually entered.
    # Preserve one source observation timestamp per market; don't mislabel an
    # intake clock as a bookmaker observation.
    source_by_game={}
    for g in today:
        source_by_game[(g["away"],g["home"])]=g["markets"]
    reverse={"MONEYLINE":"h2h","RUN_LINE":"spreads","GAME_TOTAL":"totals"}
    for row in snapshot["rows"]:
        name=row["game_id"].split("@",1)
        src=source_by_game.get(tuple(name))
        key=reverse.get(row["market_type"])
        if not src or not key or key not in src:
            raise ValueError("MLB_AUTO_PROVENANCE_GAME_MARKET_UNRESOLVED")
        pair=src[key]
        # The bound source must still have the quoted exact threshold and side.
        actual_pair=(pair["over"],pair["under"]) if key=="totals" else (pair["away"],pair["home"])
        if (int(row["price"]),int(row["paired_price"]))!=tuple(actual_pair):
            raise ValueError("MLB_AUTO_PROVENANCE_ODDS_MISMATCH")
        if key!="h2h" and abs(float(row["line"])-float(pair["line"]))>1e-9:
            raise ValueError("MLB_AUTO_PROVENANCE_LINE_MISMATCH")
        row["observed_at"]=pair["observed_at"]
        row["timestamp_source"]="PROVIDED"
        row["quote_origin"]="ODDS_API_DK_AUTO"
        row["provider_market"]=key
        row["source"]="MANUAL"  # canonical quote adapter, not the data provider
        start=parse_game_start(row["first_pitch_at"])
        if start<=now:
            raise ValueError("MLB_AUTO_ALREADY_STARTED")
    snapshot["schedule_snapshot"]=[asdict(game) for game in schedule]
    snapshot["quote_origin"]="ODDS_API_DK_AUTO"
    snapshot["captured_at_utc"]=now.isoformat()
    return snapshot


def run_mlb(raw,out,now):
    games=raw.get("games") or []
    if not games:
        return {"status":"NO_DK_GAMES","cards":[]}
    try:
        snapshot=mlb_auto_snapshot(games,now)
        if snapshot is None:
            return {"status":"NO_CURRENT_DAY_DK_GAMES","cards":[]}
    except (ValueError,TypeError,OSError) as exc:
        return {"status":"SOURCE_BIND_FAILED","reason":type(exc).__name__+":"+str(exc)[:120],"cards":[]}
    path=out/"mlb_auto_snapshot.json"
    path.write_text(json.dumps(snapshot,indent=2)+"\n")
    card=out/"mlb_auto_card.json"
    date=now.astimezone(CT).date().isoformat()
    ok,reason=call(["scripts/run_manual_mlb_snapshot.py","--input",path,"--output",card,
                    "--run-date",date,"--max-age-minutes","60"],timeout=330)
    if not ok:
        return {"status":"MODEL_UNAVAILABLE","reason":reason[:250],"cards":[]}
    md=out/"mlb_render"
    md_ok,_=call(["scripts/render_mlb_myspari_card.py",
                  "--engine-output",card,"--snapshot",path,"--pre-context",
                  "--out-dir",md],timeout=45)
    return {"status":"READY","cards":[{"date":date,"state":"READY","json":str(card),
           "md":str(md/"card.md") if md_ok else None,
           "png":image_card(card,"MLB",out/"mlb.png")}]}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--odds-dir",type=Path,default=Path("artifacts/auto_dk"))
    ap.add_argument("--out-dir",type=Path,default=Path("artifacts/auto_dk_cards"))
    args=ap.parse_args()
    args.out_dir.mkdir(parents=True,exist_ok=True)
    now=datetime.now(timezone.utc)
    results={}
    for sport,runner in (("NFL",run_nfl),("CFB",run_cfb),("MLB",run_mlb)):
        path=args.odds_dir/(sport.lower()+"_odds.json")
        try:
            raw=json.loads(path.read_text())
            results[sport]=runner(raw,args.out_dir,now)
        except (OSError,ValueError,TypeError,KeyError) as exc:
            results[sport]={"status":"SOURCE_UNAVAILABLE","reason":type(exc).__name__,
                            "cards":[]}
    results["NBA"]={"status":"CAPTURE_ONLY","cards":[],
                    "reason":"NO_PREDICTIVE_ENGINE_WIRED"}
    target=args.out_dir/"summary.json"
    target.write_text(json.dumps(results,indent=2,sort_keys=True)+"\n")
    print(json.dumps({k:{"status":v["status"],"cards":len(v["cards"])} for k,v in results.items()}))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
