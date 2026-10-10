#!/usr/bin/env python3
"""Research-only grader: immutable opening CFB spreads; separate close/final observations."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
from datetime import datetime,timezone,timedelta

SCHEMA="CFB_UNSUPPORTED_SPREAD_TRACKER_V1"

def utc(s,name):
    try:
        d=datetime.fromisoformat(str(s).replace("Z","+00:00"))
        if d.tzinfo is None or d.utcoffset() is None:
            raise ValueError("tz")
        return d.astimezone(timezone.utc)
    except (ValueError,TypeError,OverflowError) as e:
        raise ValueError("INVALID_TIME:"+name) from e

def num(x,name):
    if isinstance(x,bool): raise ValueError("INVALID_NUMBER:"+name)
    try: v=float(x)
    except (ValueError,TypeError,OverflowError) as e:
        raise ValueError("INVALID_NUMBER:"+name) from e
    if not math.isfinite(v): raise ValueError("INVALID_NUMBER:"+name)
    return v

def implied(am):
    am=num(am,"american")
    if -100<=am<100 or abs(am)>10000: raise ValueError("INVALID_AMERICAN_ODDS")
    return -am/(100-am) if am<0 else 100/(100+am)

def payout(am):
    implied(am)
    return 100/-am if am<0 else am/100

def keyed(data,label):
    if not isinstance(data,list): raise ValueError(label+"_ARRAY_REQUIRED")
    out={}
    for item in data:
        id=item.get("id") if isinstance(item,dict) else None
        if not isinstance(id,str) or not id or id in out: raise ValueError(label+"_DUPLICATE_OR_INVALID_ID")
        out[id]=item
    return out

def grade(ledger,closing,finals):
    if (ledger.get("schema")!=SCHEMA or ledger.get("official") is not False
        or ledger.get("probation") is not False or ledger.get("verified_positive_ev") is not False
        or ledger.get("staking_authority") is not False): raise ValueError("RESEARCH_LEDGER_REQUIRED")
    originals=ledger.get("contracts")
    if not isinstance(originals,list) or not originals: raise ValueError("ORIGINALS_REQUIRED")
    ids=[x["id"] for x in originals]
    if len(set(ids))!=len(ids): raise ValueError("DUPLICATE_ORIGINAL")
    close=keyed(closing,"CLOSE")
    final=keyed(finals,"FINAL")
    if set(close)-set(ids) or set(final)-set(ids): raise ValueError("UNKNOWN_OBSERVATION_ID")
    rows=[]
    for x in originals:
        id=x["id"]
        if x.get("status")!="UNSUPPORTED_RESEARCH_ONLY" or x.get("original_contract_frozen") is not True or x.get("quote_evidence_verified") is not False:
            raise ValueError("ORIGINAL_CONTRACT_NOT_FROZEN")
        home,away=x["home"],x["away"]
        if "illinois" in (home+" "+away).lower(): raise ValueError("ILLINOIS_TEAM_EXCLUDED")
        side=x["pick_team_canonical"]
        if side not in (home,away): raise ValueError("PICK_NOT_IN_MATCHUP")
        handicap=num(x["handicap"],"open_line")
        am=num(x["price_american"],"open_price")
        implied(am)
        units=num(x["stake_units"],"units")
        if units!=.25: raise ValueError("STAKE_CHANGED")
        k=utc(x["kickoff_utc"],"kickoff")
        open_at=utc(x["quote_captured_at_utc"],"opening")
        if open_at>=k: raise ValueError("OPENED_AFTER_KICKOFF")
        c=close.get(id)
        close_handicap=close_price=line_clv=price_clv_pp=None
        close_status="PENDING_CLOSE"
        if c is not None:
            if c.get("pick_team_canonical")!=side or c.get("book")!="DraftKings":
                raise ValueError("CLOSE_WRONG_BOOK_OR_SIDE")
            if not c.get("source_ref"): raise ValueError("CLOSE_SOURCE_REQUIRED")
            t=utc(c.get("observed_at_utc"),"closing")
            if not open_at<t<k or k-t>timedelta(minutes=60):
                raise ValueError("CLOSE_NOT_LAST_HOUR_PREGAME")
            close_handicap=num(c.get("handicap"),"close_handicap")
            close_price=num(c.get("price_american"),"close_price")
            implied(close_price)
            line_clv=round(handicap-close_handicap,4)
            if abs(line_clv)<1e-8:
                price_clv_pp=round(100*(implied(close_price)-implied(am)),4)
            close_status="OBSERVED_CLOSE" if c.get("verified") is True else "UNVERIFIED_CLOSE"
        f=final.get(id)
        outcome="PENDING_FINAL"
        pnl=None
        score=None
        if f is not None:
            if f.get("status")!="FINAL" or not f.get("source_ref"):
                raise ValueError("FINAL_SOURCE_REQUIRED")
            if utc(f.get("observed_at_utc"),"final")<=k:
                raise ValueError("RESULT_OBSERVED_BEFORE_KICKOFF")
            a=num(f.get("away_points"),"away_points")
            h=num(f.get("home_points"),"home_points")
            if a!=int(a) or h!=int(h) or not(0<=a<=150 and 0<=h<=150):
                raise ValueError("INVALID_FINAL_POINTS")
            margin=(h-a) if side==home else (a-h)
            settlement=margin+handicap
            outcome="WIN" if settlement>1e-9 else "LOSS" if settlement< -1e-9 else "PUSH"
            pnl=round(units*(payout(am) if outcome=="WIN" else -1 if outcome=="LOSS" else 0),6)
            score={"away_points":int(a),"home_points":int(h),"source_ref":f["source_ref"]}
        rows.append({"id":id,"matchup":away+" @ "+home,"pick":x["pick"],
           "original_handicap":handicap,"original_price_american":int(am),
           "raw_model_gap_points_unsupported":x["raw_model_gap_points"],
           "stake_units":units,"closing_handicap":close_handicap,
           "closing_price_american":close_price,"close_status":close_status,
           "line_clv_points":line_clv,"same_line_price_clv_implied_pp":price_clv_pp,
           "clv_is_not_verified_no_vig":True,"result":outcome,
           "paper_pnl_units":pnl,"final_score":score})
    settled=[r for r in rows if r["result"]!="PENDING_FINAL"]
    pnl=round(sum(r["paper_pnl_units"] for r in settled),6)
    return {"schema":"CFB_UNSUPPORTED_SPREAD_GRADE_V1",
     "source_issue":ledger["source_issue"],"official":False,"probation":False,
     "model_p":False,"positive_ev_proven":False,"betting_authority":False,
     "promotion_eligible":False,"no_backfill":True,
     "summary":{"tracked":len(rows),"nominal_stake_units":sum(r["stake_units"] for r in rows),
        "settled":len(settled),"pending_results":len(rows)-len(settled),
        "pending_closes":sum(r["close_status"]=="PENDING_CLOSE" for r in rows),
        "wins":sum(r["result"]=="WIN" for r in rows),
        "losses":sum(r["result"]=="LOSS" for r in rows),
        "pushes":sum(r["result"]=="PUSH" for r in rows),
        "paper_pnl_units":pnl,
        "paper_roi":round(pnl/sum(r["stake_units"] for r in settled),6) if settled else None},
     "rows":rows}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ("ledger","closes","results","output"):
        p.add_argument("--"+arg,type=Path,required=True)
    a=p.parse_args()
    report=grade(json.loads(a.ledger.read_text()),
        json.loads(a.closes.read_text())["observations"],
        json.loads(a.results.read_text())["results"])
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print("CFB_UNSUPPORTED_SPREAD",json.dumps(report["summary"],sort_keys=True))

if __name__=="__main__": main()
