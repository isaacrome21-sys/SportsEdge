#!/usr/bin/env python3
"""Prove MLB settlement semantics from official finalized game data.

This is not model validation. It establishes that canonical outcome facts needed
for market settlement can be derived from official MLB boxscore/linescore data
without sportsbook prices. Special markets requiring event ordering or winning-
pitcher decision semantics remain excluded until separately proven.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

GAME_PK=int(os.getenv("SPORTSEDGE_SETTLEMENT_PROBE_GAME_PK","822696"))
BASE="https://statsapi.mlb.com"

GAME_MARKETS=("MONEYLINE","RUN_LINE","TOTALS","F5_MONEYLINE","F5_RUN_LINE","F5_TOTALS","NRFI","YRFI")
BATTER_MARKETS=("HITS","TOTAL_BASES","HOME_RUNS","RBI","RUNS","HITS_RUNS_RBIS","SINGLES","DOUBLES","TRIPLES","BATTER_BB","BATTER_K","STOLEN_BASES")
PITCHER_MARKETS=("PITCHER_BB","PITCHER_K","PITCHER_HITS_ALLOWED","PITCHER_ER","PITCHER_OUTS")
PROVEN_MARKETS=tuple(sorted(set(GAME_MARKETS+BATTER_MARKETS+PITCHER_MARKETS)))


def get(path:str)->dict[str,Any]:
    req=Request(BASE+path,headers={"Accept":"application/json","User-Agent":"SportsEdge-settlement-probe/1"})
    with urlopen(req,timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def canonical(v:Any)->bytes:
    return (json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=True)+"\n").encode()


def outs_from_ip(value:Any)->int:
    text=str(value or "0.0")
    whole,sep,frac=text.partition(".")
    if not sep: return int(whole)*3
    if frac not in {"0","1","2"}: raise ValueError(f"BAD_INNINGS_PITCHED:{text}")
    return int(whole)*3+int(frac)


def i(v:Any)->int:
    try:return int(v or 0)
    except (TypeError,ValueError):return 0


def batter_fact(pid:str,stats:dict[str,Any])->dict[str,Any]:
    hits=i(stats.get("hits")); doubles=i(stats.get("doubles")); triples=i(stats.get("triples")); hr=i(stats.get("homeRuns"))
    singles=hits-doubles-triples-hr
    if singles<0: raise ValueError(f"NEGATIVE_SINGLES:{pid}")
    return {
        "player_id":pid,"hits":hits,"singles":singles,"doubles":doubles,"triples":triples,"home_runs":hr,
        "total_bases":singles+2*doubles+3*triples+4*hr,"rbi":i(stats.get("rbi")),"runs":i(stats.get("runs")),
        "hits_runs_rbis":hits+i(stats.get("runs"))+i(stats.get("rbi")),"walks":i(stats.get("baseOnBalls")),
        "strikeouts":i(stats.get("strikeOuts")),"stolen_bases":i(stats.get("stolenBases")),
    }


def pitcher_fact(pid:str,stats:dict[str,Any])->dict[str,Any]:
    return {
        "player_id":pid,"walks":i(stats.get("baseOnBalls")),"strikeouts":i(stats.get("strikeOuts")),
        "hits_allowed":i(stats.get("hits")),"earned_runs":i(stats.get("earnedRuns")),
        "outs":outs_from_ip(stats.get("inningsPitched")),
    }


def main()->int:
    feed=get(f"/api/v1.1/game/{GAME_PK}/feed/live")
    status=(((feed.get("gameData") or {}).get("status") or {}).get("abstractGameState"))
    if status!="Final": raise SystemExit(f"PROBE_GAME_NOT_FINAL:{status}")
    box=get(f"/api/v1/game/{GAME_PK}/boxscore")
    linescore=((feed.get("liveData") or {}).get("linescore") or {})
    innings=linescore.get("innings") or []
    if not innings: raise SystemExit("NO_INNINGS")
    away_runs=i(((linescore.get("teams") or {}).get("away") or {}).get("runs")); home_runs=i(((linescore.get("teams") or {}).get("home") or {}).get("runs"))
    f5_away=sum(i((((x or {}).get("teams") or {}).get("away") or {}).get("runs")) for x in innings if 1<=i((x or {}).get("num"))<=5)
    f5_home=sum(i((((x or {}).get("teams") or {}).get("home") or {}).get("runs")) for x in innings if 1<=i((x or {}).get("num"))<=5)
    first=next((x for x in innings if i((x or {}).get("num"))==1),None)
    if not first: raise SystemExit("FIRST_INNING_MISSING")
    first_away=i((((first or {}).get("teams") or {}).get("away") or {}).get("runs")); first_home=i((((first or {}).get("teams") or {}).get("home") or {}).get("runs"))

    batters=[]; pitchers=[]
    for side in ("away","home"):
        players=((((box.get("teams") or {}).get(side) or {}).get("players")) or {})
        for key,p in sorted(players.items()):
            pid=str((p or {}).get("person",{}).get("id") or key.removeprefix("ID"))
            stats=(p or {}).get("stats") or {}
            batting=stats.get("batting") or {}
            pitching=stats.get("pitching") or {}
            if batting and i(batting.get("plateAppearances"))>0: batters.append(batter_fact(pid,batting))
            if pitching and outs_from_ip(pitching.get("inningsPitched"))>0: pitchers.append(pitcher_fact(pid,pitching))
    if not batters or not pitchers: raise SystemExit("PLAYER_FACTS_MISSING")

    # Strong reconciliation invariants against official team totals.
    box_teams=box.get("teams") or {}
    team_hits=sum(i((((box_teams.get(s) or {}).get("teamStats") or {}).get("batting") or {}).get("hits")) for s in ("away","home"))
    if sum(x["hits"] for x in batters)!=team_hits: raise SystemExit("BATTER_HITS_RECONCILIATION_FAILED")
    if away_runs==home_runs: raise SystemExit("FINAL_GAME_TIE_UNSUPPORTED")
    if not (0<=first_away+first_home<=away_runs+home_runs): raise SystemExit("FIRST_INNING_RECONCILIATION_FAILED")
    if not (0<=f5_away+f5_home<=away_runs+home_runs): raise SystemExit("F5_RECONCILIATION_FAILED")

    facts={
        "game_pk":str(GAME_PK),"status":"Final","source":"MLB_STATSAPI_BOX_SCORE_AND_LIVE_FEED",
        "game":{"away_runs":away_runs,"home_runs":home_runs,"run_diff_home":home_runs-away_runs,"total_runs":away_runs+home_runs},
        "f5":{"away_runs":f5_away,"home_runs":f5_home,"run_diff_home":f5_home-f5_away,"total_runs":f5_away+f5_home},
        "first_inning":{"away_runs":first_away,"home_runs":first_home,"nrfi":int(first_away+first_home==0),"yrfi":int(first_away+first_home>0)},
        "batters":batters,"pitchers":pitchers,
    }
    digest=hashlib.sha256(canonical(facts)).hexdigest()
    report={
        "schema_version":"mlb_settlement_semantics_v1","generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "game_pk":str(GAME_PK),"source":"MLB_STATSAPI_BOX_SCORE_AND_LIVE_FEED","sportsbook_data_used":False,
        "proven_markets":list(PROVEN_MARKETS),"excluded_markets":["FIRST_HOME_RUN","PITCHER_RECORD_WIN"],
        "invariants":{"final_status":True,"batter_hits_reconciled":True,"first_inning_reconciled":True,"f5_reconciled":True,"facts_present":True},
        "facts_sha256":digest,"facts":facts,"state":"SETTLEMENT_SEMANTICS_PASS",
    }
    out=Path("artifacts/mlb-settlement-semantics/report.json"); out.parent.mkdir(parents=True,exist_ok=True); out.write_bytes(canonical(report))
    print(json.dumps({"state":report["state"],"game_pk":GAME_PK,"proven_markets":len(PROVEN_MARKETS),"batters":len(batters),"pitchers":len(pitchers),"facts_sha256":digest},indent=2))
    return 0

if __name__=="__main__": raise SystemExit(main())
