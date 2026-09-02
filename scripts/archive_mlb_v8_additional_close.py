#!/usr/bin/env python3
"""Capture additional MLB market closes for V8 at strictly prestart T0 snapshots.

This is deliberately close-only. Exact decision quotes come from the immutable
prediction journal; this collector supplies the missing close benchmark without
polling expensive player-prop markets throughout the day.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json, os
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sportsedge.mlb_evidence_archive import EvidenceRow, FORWARD_EPOCH_UTC, PIT_TIMESTAMPED, append_jsonl, bytes_sha256, canonical_json_sha256, iso_utc

ODDS_BASE="https://api.the-odds-api.com/v4"; SPORT_KEY="baseball_mlb"; MLB_SCHEDULE="https://statsapi.mlb.com/api/v1/schedule"
FORWARD_EPOCH=datetime.fromisoformat(FORWARD_EPOCH_UTC.replace("Z","+00:00"))
DEFAULT_MARKETS=(
    "alternate_spreads","alternate_totals","team_totals","alternate_team_totals",
    "batter_home_runs","batter_hits","batter_total_bases","batter_rbis","batter_runs_scored","batter_hits_runs_rbis",
    "batter_singles","batter_doubles","batter_triples","batter_walks","batter_strikeouts","batter_stolen_bases",
    "pitcher_strikeouts","pitcher_hits_allowed","pitcher_walks","pitcher_earned_runs","pitcher_outs","pitcher_record_a_win",
    "totals_1st_1_innings","alternate_totals_1st_1_innings",
    "h2h_1st_5_innings","spreads_1st_5_innings","totals_1st_5_innings",
    "batter_first_home_run",
)

def _utc(value: Any)->datetime:
    t=str(value or "").replace("Z","+00:00"); d=datetime.fromisoformat(t)
    if d.tzinfo is None or d.utcoffset() is None: d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def _schedule(slate:str):
    uri=f"{MLB_SCHEDULE}?"+urlencode({"sportId":1,"date":slate,"gameType":"R","hydrate":"team"})
    with urlopen(Request(uri,headers={"Accept":"application/json","User-Agent":"SportsEdge-V8-Close/1.0"}),timeout=30) as r: payload=json.loads(r.read())
    out=[]
    for d in payload.get("dates",[]):
        for g in d.get("games",[]):
            if not g.get("gameDate"): continue
            out.append({"game_pk":str(g.get("gamePk")),"commence_time":iso_utc(g["gameDate"],"gameDate"),"home_team":str((((g.get("teams") or {}).get("home") or {}).get("team") or {}).get("name") or ""),"away_team":str((((g.get("teams") or {}).get("away") or {}).get("team") or {}).get("name") or "")})
    return out

def _norm(v): return " ".join(str(v or "").lower().replace(".","").split())
def _match_game(event,schedule):
    best=None
    for g in schedule:
        if _norm(g["home_team"])!=_norm(event.get("home_team")) or _norm(g["away_team"])!=_norm(event.get("away_team")): continue
        delta=abs((_utc(g["commence_time"])-_utc(event.get("commence_time"))).total_seconds())
        if delta<=20*60 and (best is None or delta<best[0]): best=(delta,g)
    return None if best is None else best[1]

def _keys():
    out=[]
    for n in ("SPORTSEDGE_ODDS_API_KEY","SPORTSEDGE_ODDS_API_KEY_2","SPORTSEDGE_ODDS_API_KEY_3","SPORTSEDGE_ODDS_API_KEY_4"):
        v=os.environ.get(n,"").strip()
        if v and v not in out: out.append(v)
    return out

def _latest_t0(raw_root: Path):
    best=None
    for p in raw_root.glob("status/*/*.json"):
        try: row=json.loads(p.read_text())
        except Exception: continue
        if str(row.get("status")) not in {"CAPTURED","INCOMPLETE_CAPTURE"}: continue
        if str(row.get("capture_window"))!="T0": continue
        raw=Path(str(row.get("raw_file") or ""))
        if not raw.is_file(): continue
        ts=_utc(row.get("run_at_utc"))
        if best is None or ts>best[0]: best=(ts,row,raw)
    return best

def _fetch(event_id:str,markets:str,books:str):
    keys=_keys(); attempts=[]
    if not keys: raise RuntimeError("ODDS_API_KEY_REQUIRED")
    for slot,key in enumerate(keys,1):
        params={"apiKey":key,"bookmakers":books,"markets":markets,"oddsFormat":"american","dateFormat":"iso"}
        uri=f"{ODDS_BASE}/sports/{SPORT_KEY}/events/{event_id}/odds?{urlencode(params)}"
        public=f"{ODDS_BASE}/sports/{SPORT_KEY}/events/{event_id}/odds?{urlencode({k:v for k,v in params.items() if k!='apiKey'})}"
        try:
            with urlopen(Request(uri,headers={"Accept":"application/json","User-Agent":"SportsEdge-V8-Close/1.0"}),timeout=35) as r:
                raw=r.read(); headers={str(k).lower():str(v) for k,v in r.headers.items()}
            return raw,headers,public,slot
        except HTTPError as exc:
            attempts.append(f"slot={slot}:HTTP_{exc.code}")
            if exc.code not in {401,403,429}: break
        except URLError as exc: attempts.append(f"slot={slot}:URL:{exc.reason}")
        except Exception as exc: attempts.append(f"slot={slot}:{type(exc).__name__}:{exc}")
    raise RuntimeError("ADDITIONAL_CLOSE_FETCH_FAILED:"+"|".join(attempts))

def _side(event,market,outcome):
    name=str(outcome.get("name") or ""); desc=str(outcome.get("description") or "").strip() or None
    if name.lower() in {"over","under","yes","no"}: return name.lower(),desc
    if name==event.get("home_team"): return "home",desc
    if name==event.get("away_team"): return "away",desc
    return name.lower().replace(" ","_"),desc

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--raw-root",default="artifacts/raw_odds"); p.add_argument("--output-root",default="artifacts/v8_forward"); p.add_argument("--markets",default=",".join(DEFAULT_MARKETS)); p.add_argument("--books",default=os.environ.get("SPORTSEDGE_ODDS_BOOKMAKERS","draftkings,fanduel,betmgm,williamhill_us,pinnacle")); p.add_argument("--daily-credit-cap",type=int,default=int(os.environ.get("SPORTSEDGE_V8_ADDITIONAL_CLOSE_DAILY_CAP","500"))); args=p.parse_args(argv)
    raw_root=Path(args.raw_root); out=Path(args.output_root); latest=_latest_t0(raw_root)
    if latest is None:
        print(json.dumps({"status":"SKIP_NO_T0_CAPTURE"})); return 0
    observed,status,raw_path=latest
    if observed<FORWARD_EPOCH:
        print(json.dumps({"status":"SKIP_PRE_V8_EPOCH","observed_at_utc":observed.isoformat()})); return 0
    base=json.loads(raw_path.read_text())
    if not isinstance(base,list): raise RuntimeError("T0 raw odds payload not list")
    eligible=[]; poststart=[]
    for event in base:
        try: commence=_utc(event.get("commence_time"))
        except Exception: continue
        if observed>=commence:
            poststart.append(str(event.get("id") or "")); continue
        # T0 raw capture is only valid as close when no more than 8m prestart.
        if (commence-observed).total_seconds()<=8*60: eligible.append(event)
    schedule=_schedule(str(status.get("slate_date_ct")))
    markets=[m for m in args.markets.split(",") if m]
    estimated=len(eligible)*len(markets)
    if estimated>args.daily_credit_cap:
        manifest={"status":"BLOCKED_DAILY_CREDIT_CAP","estimated_credits":estimated,"cap":args.daily_credit_cap,"eligible_events":len(eligible),"markets":markets,"poststart_rejected":poststart}
        out.mkdir(parents=True,exist_ok=True); (out/"additional_close_manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n"); print(json.dumps(manifest,sort_keys=True)); return 3
    rows=[]; acquisitions=[]
    for event in eligible:
        game=_match_game(event,schedule)
        if game is None:
            acquisitions.append({"event_id":event.get("id"),"status":"UNMATCHED_MLB_GAME"}); continue
        raw,headers,public,slot=_fetch(str(event.get("id")),",".join(markets),args.books)
        payload=json.loads(raw); source_sha=bytes_sha256(raw)
        raw_dest=out/str(status.get("slate_date_ct"))/"additional_close_raw"/f"{event.get('id')}_{source_sha}.json"; raw_dest.parent.mkdir(parents=True,exist_ok=True); raw_dest.write_bytes(raw)
        for book in payload.get("bookmakers") or []:
            for market in book.get("markets") or []:
                mkey=str(market.get("key") or ""); update=market.get("last_update") or book.get("last_update")
                for outcome in market.get("outcomes") or []:
                    if outcome.get("price") in (None,""): continue
                    side,participant=_side(payload,mkey,outcome); line=outcome.get("point")
                    rows.append(EvidenceRow(
                        source_name="SPORTSEDGE_V8_FORWARD",source_uri=public,source_record_sha256=source_sha,
                        collected_at_utc=observed.isoformat().replace("+00:00","Z"),observed_at_utc=observed.isoformat().replace("+00:00","Z"),
                        event_id=str(game["game_pk"]),commence_time_utc=str(game["commence_time"]),home_team=str(game["home_team"]),away_team=str(game["away_team"]),
                        market=mkey,side=side,bookmaker=str(book.get("key") or "") or None,american_odds=float(outcome["price"]),line=None if line in (None,"") else float(line),participant=participant,checkpoint="CLOSE_PRESTART",evidence_class=PIT_TIMESTAMPED,
                        provider_last_update_utc=None if not update else iso_utc(update,"provider_update"),provider_event_id=str(event.get("id") or "") or None,source_tier="A_FORWARD_IMMUTABLE_ADDITIONAL_CLOSE",
                        metadata={"upstream_provider":"THE_ODDS_API","mlb_game_pk_status":"MATCHED_STATSAPI","raw_file":str(raw_dest)},
                    ).as_record())
        acquisitions.append({"event_id":event.get("id"),"raw_sha256":source_sha,"raw_file":str(raw_dest),"key_slot":slot,"request_cost":headers.get("x-requests-last"),"requests_remaining":headers.get("x-requests-remaining")})
    slate=str(status.get("slate_date_ct")); n=append_jsonl(out/slate/"additional_close_snapshots.jsonl",rows)
    manifest={"status":"CAPTURED" if eligible else "NO_PRESTART_T0_EVENTS","slate_date_ct":slate,"observed_at_utc":observed.isoformat(),"eligible_events":len(eligible),"poststart_rejected":poststart,"market_count":len(markets),"estimated_credits":estimated,"rows_written":n,"acquisitions":acquisitions,"first_home_run_shape_status":"RAW_CAPTURE_ONLY_N_WAY_VALIDATION_STILL_REQUIRED","exact_threshold_rule":"PAIR_ONLY_IF_CLOSE_CONTAINS_ORIGINAL_WAGER_LINE"}
    manifest["manifest_sha256"]=canonical_json_sha256(manifest); out.mkdir(parents=True,exist_ok=True); (out/"additional_close_manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n"); print(json.dumps(manifest,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
