#!/usr/bin/env python3
"""CFB market-consensus PAPER card.

This is deliberately not a predictive model. It compares DraftKings prices with a
cross-book no-vig consensus and emits research-only paper candidates when DK is
materially better than consensus. It creates no Model_P, Truth Gate, promotion,
eligibility, staking, evidence-clock, backfill, or OFFICIAL authority.
"""
from __future__ import annotations
import argparse, json, os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ODDS_URL="https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds"
BOOKS=("draftkings","fanduel","betmgm","caesars")

def implied(a):
    a=float(a)
    return 100/(100+a) if a>0 else (-a)/((-a)+100)

def fetch(key):
    q=urlencode({"apiKey":key,"regions":"us","markets":"h2h,spreads,totals",
                 "oddsFormat":"american","bookmakers":",".join(BOOKS)})
    with urlopen(Request(ODDS_URL+"?"+q),timeout=30) as r:
        return json.loads(r.read().decode())

def pair_probs(outcomes):
    if len(outcomes)!=2: return None
    ps=[implied(x["price"]) for x in outcomes]; s=sum(ps)
    if s<=0:return None
    return {str(o["name"]):p/s for o,p in zip(outcomes,ps)}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--output",default="artifacts/cfb/cfb_paper_market_card.json")
    ap.add_argument("--min-edge",type=float,default=0.02); args=ap.parse_args()
    key=(os.getenv("ODDS_API_KEY") or os.getenv("SPORTSEDGE_ODDS_API_KEY") or "").strip()
    if not key: raise SystemExit("CFB_PAPER_ODDS_API_KEY_REQUIRED")
    now=datetime.now(timezone.utc); events=fetch(key); candidates=[]; observed=0
    for ev in events:
        start=datetime.fromisoformat(str(ev["commence_time"]).replace("Z","+00:00"))
        if start<=now: continue
        markets={}
        for bk in ev.get("bookmakers",[]):
            bkey=bk.get("key")
            for m in bk.get("markets",[]):
                market=m.get("key")
                if market not in {"h2h","spreads","totals"}: continue
                outs=m.get("outcomes",[])
                # Spread/total consensus is meaningful only at the identical line.
                if market=="h2h":
                    line_key=None
                else:
                    pts=sorted(float(x.get("point",0)) for x in outs)
                    if len(pts)!=2: continue
                    line_key=tuple(pts)
                probs=pair_probs(outs)
                if not probs: continue
                markets.setdefault((market,line_key),{})[bkey]={"outcomes":outs,"probs":probs}
        for (market,line_key),books in markets.items():
            dk=books.get("draftkings")
            peers=[v for k,v in books.items() if k!="draftkings"]
            if not dk or len(peers)<2: continue
            for o in dk["outcomes"]:
                name=str(o["name"]); observed+=1
                vals=[p["probs"].get(name) for p in peers if name in p["probs"]]
                if len(vals)<2: continue
                consensus=sum(vals)/len(vals); dk_raw=implied(o["price"])
                # EV using market-consensus probability, not Model_P.
                dec=1+(100/abs(float(o["price"])) if float(o["price"])<0 else float(o["price"])/100)
                ev=consensus*(dec-1)-(1-consensus)
                edge=consensus-dk_raw
                if edge>=args.min_edge and ev>0:
                    candidates.append({"game_id":str(ev.get("id") if isinstance(ev,dict) else ev),
                        "away_team":evnt_away if False else str(ev.get("away_team",""))})
    # Rebuild candidates without accidental event-variable shadowing.
    candidates=[]
    for event in events:
        start=datetime.fromisoformat(str(event["commence_time"]).replace("Z","+00:00"))
        if start<=now: continue
        grouped={}
        for bk in event.get("bookmakers",[]):
            for m in bk.get("markets",[]):
                if m.get("key")!="h2h": continue
                probs=pair_probs(m.get("outcomes",[]))
                if probs: grouped[bk.get("key")]={"outcomes":m["outcomes"],"probs":probs}
        dk=grouped.get("draftkings"); peers=[v for k,v in grouped.items() if k!="draftkings"]
        if not dk or len(peers)<2: continue
        for o in dk["outcomes"]:
            name=str(o["name"]); vals=[p["probs"].get(name) for p in peers if name in p["probs"]]
            if len(vals)<2: continue
            consensus=sum(vals)/len(vals); price=float(o["price"]); raw=implied(price)
            dec=1+(100/abs(price) if price<0 else price/100); evd=consensus*(dec-1)-(1-consensus)
            edge=consensus-raw
            if edge>=args.min_edge and evd>0:
                candidates.append({"game_id":str(event.get("id")),"away_team":event.get("away_team"),
                    "home_team":event.get("home_team"),"commence_time":event.get("commence_time"),
                    "market":"MONEYLINE","side":name,"draftkings_odds":price,
                    "market_consensus_no_vig_p":consensus,"draftkings_raw_implied_p":raw,
                    "market_consensus_edge":edge,"market_consensus_ev_per_dollar":evd,
                    "peer_books_used":len(vals),"status":"PAPER_MARKET_CONSENSUS_ONLY",
                    "model_p":None,"truth_gate":False,"official":False})
    candidates.sort(key=lambda x:x["market_consensus_ev_per_dollar"],reverse=True)
    payload={"schema":"CFB_PAPER_MARKET_CARD_V1","generated_at_utc":now.isoformat(),
             "status":"PAPER_ONLY","method":"CROSS_BOOK_NO_VIG_CONSENSUS_V1",
             "min_edge":args.min_edge,"candidates":candidates,
             "authority":{"model_p":False,"truth_gate":False,"promotion":False,"eligibility":False,
                          "staking":False,"evidence_clock":False,"backfill":False,"official":False}}
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"status":"PAPER_ONLY","candidate_count":len(candidates),"output":str(out)},sort_keys=True))
if __name__=="__main__": main()
