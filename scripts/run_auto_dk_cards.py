#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# SUPERSEDED ROUTE (2026-10-12): the ONE canonical RUN IT card path is
# artifacts/run_it_full.py (run_full). This entry point is retained for
# reference/replay only and must not be treated as a canonical card source.
# ---------------------------------------------------------------------------
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
import csv
import gzip
import re
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
    diagnostics=(p.stdout or "")+"\n"+(p.stderr or "")
    if len(diagnostics)>20000:
        diagnostics=diagnostics[:6000]+"\n...TRUNCATED...\n"+diagnostics[-14000:]
    return p.returncode==0,diagnostics


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


def _nfl_prop_failure_status(diagnostics: str) -> str:
    # Bad independently verified event-clock identity is a quote failure,
    # not missing model probability. No provider retry here.
    if ("QUOTE_KICKOFF_INDEPENDENT_SCHEDULE_MISMATCH" in diagnostics
            or "quote_kickoff:" in diagnostics
            or "SCHEDULE_MATCH_REQUIRED" in diagnostics):
        return "QUOTE_EVENT_REJECTED"
    return "MODEL_UNAVAILABLE"


def run_nfl(raw, out, now):
    cards=[]
    days=nfl_tickets(raw.get("games") or [],now,
                     source=raw.get("source") or "ODDS_API_DK_AUTO")
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
        entry={"date":day,"state":"READY","json":str(card),
               "md":str(md_dir/"card.md") if markdown else None,
               "png":image_card(card,"NFL",out/("nfl_"+day+".png"))}
        props=out/("nfl_prop_ticket_"+day+".json")
        if props.is_file():
            try:
                prop_ticket=json.loads(props.read_text(encoding="utf-8"))
                # Only games with actual paired player offers run the expensive
                # research sim; the verified game-line card is already written.
                targeted=[g for g in prop_ticket.get("games") or []
                          if any(m.get("player") for m in g.get("markets") or [])]
                if targeted and ok and history.is_file():
                    prop_ticket["games"]=targeted
                    targeted_file=out/("nfl_prop_target_"+day+".json")
                    targeted_file.write_text(json.dumps(prop_ticket,indent=2)+"\n")
                    prop_card=out/("nfl_prop_research_"+day+".json")
                    success,why=call(["scripts/run_nfl_unified_lines_card.py",
                        "--input",targeted_file,"--history",history,
                        "--output",prop_card,"--n-sims","20000"],timeout=240)
                    if success and prop_card.is_file():
                        row=json.loads(prop_card.read_text(encoding="utf-8"))
                        entry["props"]={"status":"RESEARCH_ONLY",
                                        "json":str(prop_card),
                                        "paired_quotes":sum(len([m for m in g.get("markets") or []
                                            if m.get("player")]) for g in targeted),
                                        "priced_model_rows":sum(1 for r in row.get("rows") or []
                                           if r.get("status")=="PRICED"),
                                        "selected_research_rows":len(row.get("selected_rows") or []),
                                        "source_status":row.get("source_status")}
                    else:
                        entry["props"]={"status":_nfl_prop_failure_status(why),
                                        "reason":why[:550]}
                elif targeted:
                    entry["props"]={"status":"MODEL_UNAVAILABLE",
                                    "reason":"PIT_NFLVERSE_HISTORY_REQUIRED"}
                else:
                    entry["props"]={"status":"NO_PAIRED_DK_PROPS"}
            except (OSError,TypeError,ValueError,KeyError) as exc:
                entry["props"]={"status":"PROP_RESEARCH_INVALID",
                                "reason":type(exc).__name__}
        cards.append(entry)
    return {"status":"READY" if any(x["state"]=="READY" for x in cards) else "MODEL_UNAVAILABLE",
            "history":"NFLVERSE" if ok else "MISSING",
            "cards":cards}


def _cfb_school_matches(book_name: str, schedule_name: str) -> bool:
    """Match a sportsbook mascot-qualified label ONLY to its schedule school.

    The independent kickoff, opponent and unique-game tests in
    bind_cfb_sdv_games are mandatory. A partial home-only match is insufficient.
    """
    clean=lambda text: " ".join(re.sub(r"[^a-z0-9 ]"," ",str(text).casefold()).split())
    book,school=clean(book_name),clean(schedule_name)
    if not school: return False
    if book==school: return True
    if not book.startswith(school+" "): return False
    suffix=book[len(school)+1:].split()
    # A different school's name must not be confused for a mascot
    # (Florida State vs Florida; Delaware State vs Delaware).
    other_school_words={"state","tech","atlantic","international","southern",
        "northern","eastern","western","central","north","south","east","west",
        "ohio","poly","a","am","monroe","lafayette","el","san"}
    if suffix and suffix[0] in other_school_words:
        # SportsDataverse lists Sam Houston State as Sam Houston.
        return school=="sam houston" and suffix[0]=="state"
    return True


def bind_cfb_sdv_games(games: list, directory: Path, now: datetime):
    """Bind DK events to 2026 SDV schedule with both teams and exact kickoff.

    No inferred week numbers. The downstream SDV loader separately verifies
    the full SHA-pinned source receipt and prior-week feature provenance.
    """
    target=directory/"cfb_schedules_2026.csv.gz"
    if not target.is_file() or not (directory/"receipt.json").is_file():
        return {},[{"matchup":g.get("away","")+" @ "+g.get("home",""),
                    "reason":"SDV_SCHEDULE_UNAVAILABLE"} for g in games]
    with gzip.open(target,"rt",encoding="utf-8-sig",newline="") as fh:
        schedule=list(csv.DictReader(fh))
    groups=defaultdict(list)
    missing=[]
    for game in games:
        start=datetime.fromisoformat(game["commence_time"].replace("Z","+00:00")).astimezone(timezone.utc)
        eligible=[]
        for row in schedule:
            if row.get("season")!="2026" or row.get("season_type","").lower() not in {"regular","2"}:
                continue
            if str(row.get("fbs_game")).lower() not in {"true","1"}:
                continue
            if str(row.get("completed")).lower() in {"true","1"}:
                continue
            try:
                when=datetime.fromisoformat(row["start_date"].replace("Z","+00:00")).astimezone(timezone.utc)
            except (KeyError,ValueError):
                continue
            if when<=now or abs((when-start).total_seconds())>900:
                continue
            if _cfb_school_matches(game["away"],row["away_team"]) and _cfb_school_matches(game["home"],row["home_team"]):
                eligible.append((row,when))
        if len(eligible)!=1:
            missing.append({"matchup":game["away"]+" @ "+game["home"],
                            "reason":"SDV_GAME_IDENTITY_OR_KICKOFF_NOT_UNIQUE",
                            "matching_schedule_games":len(eligible)})
            continue
        row,when=eligible[0]
        # Pass the provider's numeric game week and school identity to the
        # selected SDV engine. The DK paired quotes and peer lines are unchanged.
        adapted=dict(game,away=row["away_team"],home=row["home_team"],
                     commence_time=when.isoformat(),
                     schedule_game_id=row["game_id"],
                     source_game_name=game["away"]+" @ "+game["home"])
        groups[(int(row["season"]),int(row["week"]))].append(adapted)
    return dict(groups),missing


def run_cfb(raw, out, now):
    directory=out/"cfb_public"
    try:
        by_week,unmatched=bind_cfb_sdv_games(raw.get("games") or [],directory,now)
    except (OSError,ValueError,TypeError) as exc:
        return {"status":"SDV_BINDING_UNAVAILABLE","reason":type(exc).__name__,
                "cards":[],"unmatched_games":len(raw.get("games") or [])}
    (out/"cfb_unmatched_games.json").write_text(json.dumps(unmatched,indent=2)+"\n")
    if not by_week:
        # Save the paired DK odds in the collection artifact; do not guess an
        # ESPN competition week just to claim a scored game.
        return {"status":"DK_QUOTES_ONLY_NO_SDV_MATCH","cards":[],
                "unmatched_games":len(unmatched)}
    out_cards=[]
    for (season,week),games in sorted(by_week.items()):
        board=cfb_compact(games)
        card=out/f"cfb_{season}_w{week}_card.json"
        cmd=["scripts/run_cfb_sdv_card_v2.py","--board-json",json.dumps(board),
             "--season",season,"--week",week,"--asof",now.isoformat(),
             "--sdv-live-dir",directory,"--output",card]
        env=os.environ.copy()
        env["CFB_SHARP_FETCH"]="0" # Peer quotes are included; no second paid fetch.
        env["CFB_SDV_MAX_RETRY_SLEEP_SECONDS"]="10"
        success,reason=call(cmd,timeout=300,env=env)
        (out/f"cfb_{season}_w{week}_diagnostics.log").write_text(reason,encoding="utf-8")
        if success:
            payload=json.loads(card.read_text(encoding="utf-8"))
            state="MODEL_READY" if payload.get("model_status","").startswith("MODEL") else "QUOTES_ONLY_MODEL_UNAVAILABLE"
            out_cards.append({"season":season,"week":week,"state":state,
                              "model_status":payload.get("model_status"),
                              "priced_rows":sum(r.get("model_p") is not None for r in payload.get("results") or []),
                              "json":str(card),"png":image_card(card,"CFB",out/f"cfb_w{week}.png")})
        else:
            out_cards.append({"season":season,"week":week,"state":"MODEL_UNAVAILABLE",
                              "reason":reason[:500]})
    status=("MODEL_READY" if any(x["state"]=="MODEL_READY" for x in out_cards)
            else "QUOTES_ONLY_MODEL_UNAVAILABLE")
    return {"status":status,"cards":out_cards,"unmatched_games":len(unmatched)}


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
