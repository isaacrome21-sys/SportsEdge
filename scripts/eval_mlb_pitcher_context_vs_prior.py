#!/usr/bin/env python3
"""2026 forward evaluation: existing opponent-adjusted K/outs vs capped older starts.

Fixed cohort: top 30 2025 innings-pitched leaders, selected from a prior season.
Heldout 2026 starts only. The current validated opponent adjustment is applied
unchanged to the recent 10 starts (the production baseline); the research
candidate additionally applies that same opponent factor to disjoint starts
11-30 and caps their aggregate strength at recent effective n. No price fitting,
no use of same-day or later outcomes, no live model promotion.

This is NOT a full benchmark of lineup-adjusted K or postseason workloads.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import urlopen

from scripts.eval_mlb_pitcher_2026_cohort import select_2025_leaders
from scripts.eval_mlb_pitcher_window_blend import MARKET_LINES, _pitcher_pool, summarize
from sportsedge.mlb_empirical_bayes import posterior_settlement_mass
from sportsedge.mlb_generic_features import MLBGenericHistorySource, _number, _read_json
from sportsedge.mlb_opp_k_context import build_index as build_k_index
from sportsedge.mlb_opp_outs_context import build_index as build_outs_index
from sportsedge.pitcher_joint_engine import price_pitcher_market
from sportsedge.source_lineage import canonical_json_sha256

VERSION = "mlb_pitcher_2026_opponent_adjusted_capped_prior_bakeoff_v1"
SELECTED_MARKETS = ("PITCHER_K", "PITCHER_OUTS")
MIN_HISTORY = 15
MIN_PITCHERS = 15
MAX_PRIOR = 20
RECENT_N = 10
BETA = {"PITCHER_K":1.0,"PITCHER_OUTS":-0.25}
STAT = {"PITCHER_K":"strikeouts","PITCHER_OUTS":"outs"}
CAP = {"PITCHER_K":20,"PITCHER_OUTS":27}


def observed_starts(source: MLBGenericHistorySource, pid: int, target: date) -> list[dict[str,Any]]:
    raw=source.player_rows(player_id=pid,group="pitching",target_date=target)
    own=[r for r in raw if _number(r["stat"].get("gamesStarted",0),"gamesStarted")>=1]
    joint=_pitcher_pool(own)
    if len(joint)!=len(own):
        raise ValueError("Pitcher history misaligned")
    return [{"date":r["date"].isoformat(),"opponent_id":r.get("opponent_id"),
             "row":v} for r,v in zip(own,joint)]


def adjusted_over_mass(rows: list[dict[str,Any]], *, index, market: str,
                       target_rel: float, line: float) -> float:
    if not rows: raise ValueError("Empty pitcher history")
    if not isfinite(target_rel) or target_rel<=0: raise ValueError("Bad opponent index")
    total=0.0
    for r in rows:
        oid=r["opponent_id"]
        if not isinstance(oid,int) or oid<=0: raise ValueError("Missing strictly-prior opponent")
        d=r["date"]
        rel=index.rel(oid,int(d[:4]),d)
        if not isfinite(rel) or rel<=0: raise ValueError("Invalid historical opponent index")
        x=float(r["row"][STAT[market]])*(target_rel/rel)**BETA[market]
        x=min(max(x,0.0),float(CAP[market]))
        lower=int(x)
        fraction=x-lower
        total+=(1-fraction)*float(lower>line)+fraction*float(lower+1>line)
    return total/len(rows)


def compare_one(rows: list[dict[str,Any]], *, index, market: str, line: float,
                target_opponent: int, target_date: str) -> tuple[float,float]:
    recent=rows[-RECENT_N:]
    older=rows[-(RECENT_N+MAX_PRIOR):-RECENT_N]
    if len(recent)!=RECENT_N or len(older)<5:
        raise ValueError("Insufficient frozen history")
    tr=index.rel(target_opponent,int(target_date[:4]),target_date)
    if not isfinite(tr) or tr<=0: raise ValueError("No target opponent index")
    rels=[index.rel(r["opponent_id"],int(r["date"][:4]),r["date"]) for r in recent]
    adj={"market":market,"beta":BETA[market],"target_rel":tr,"history_rel":rels,
         "opponent_team_id":target_opponent}
    if market=="PITCHER_OUTS":
        adj["index"]="obidx"
    features={"history_pool":[r["row"] for r in recent],
              "opp_k_adjustment" if market=="PITCHER_K" else "opp_outs_adjustment":adj}
    baseline=price_pitcher_market({"market":market,"side":"OVER","line":line,"features":features})
    recent_raw=baseline["meta"]["raw_empirical_p"]
    older_raw=adjusted_over_mass(older,index=index,market=market,
                                target_rel=tr,line=line)
    strength=min(float(len(recent)),float(len(older)))
    combined=(len(recent)*recent_raw+strength*older_raw)/(len(recent)+strength)
    post=posterior_settlement_mass(over_mass=combined,under_mass=1-combined,
                                   push_mass=0,effective_n=len(recent)+strength,
                                   has_push=False)
    return float(baseline["model_p"]),float(post["p_over"])


def per_pitcher(source: MLBGenericHistorySource, item: Mapping[str,Any], target: date,
                indexes: Mapping[str,Any]) -> dict[str,Any]:
    starts=observed_starts(source,int(item["pitcher_id"]),target)
    result=dict(item,available_starts=len(starts))
    records=[]
    rejected={"SAME_DAY":0,"MISSING_OPPONENT":0,"INTERNAL_ERROR":0}
    for i in range(MIN_HISTORY,len(starts)):
        held=starts[i]
        if held["date"][:4]!="2026": continue
        training=starts[:i]
        if any(r["date"]>=held["date"] for r in training):
            rejected["SAME_DAY"]+=1
            continue
        own=training[-(RECENT_N+MAX_PRIOR):]
        if (not isinstance(held["opponent_id"],int)) or any(
                not isinstance(r["opponent_id"],int) for r in own):
            rejected["MISSING_OPPONENT"]+=1
            continue
        for market in SELECTED_MARKETS:
            for line in MARKET_LINES[market]:
                try:
                    base,candidate=compare_one(training,index=indexes[market],market=market,
                        line=line,target_opponent=held["opponent_id"],target_date=held["date"])
                except (ValueError, KeyError, TypeError) as exc:
                    # Explicit failure accounting rather than a silent successful score.
                    raise ValueError(f"Invalid index for {item['pitcher_id']} {held['date']} {market}: {exc}") from exc
                records.append({
                    "market":market,"line":line,"date":held["date"],
                    "actual_over":float(held["row"][STAT[market]]>line),
                    "p_recent_only":base,"p_recent_plus_capped_prior":candidate,
                    "baseline":"EXISTING_OPP_ADJUSTED_RECENT_10",
                    "candidate":"EXISTING_OPP_ADJUSTED_RECENT_10_PLUS_ADJUSTED_OLDER_20",
                    "target_opponent":held["opponent_id"],"training_last_date":training[-1]["date"],
                })
    result["skipped_games"]=rejected
    result["holdout_games"]=len({r["date"] for r in records})
    result["status"]="EVALUATED" if result["holdout_games"]>=5 else "INSUFFICIENT_2026_HOLDOUT"
    if records:
        s=summarize(records)
        result["overall"]=s["overall"]
        result["markets"]=s["markets"]
    result["records"]=records
    return result


def run(target:date, *, workers:int=6, count:int=30)->dict[str,Any]:
    if target.year!=2026: raise ValueError("Locked to 2026 holdout")
    source=MLBGenericHistorySource()
    query=urlencode({"leaderCategories":"inningsPitched","statGroup":"pitching",
                     "season":2025,"sportId":1,"gameType":"R","limit":count})
    leaders=select_2025_leaders(_read_json(
        f"https://statsapi.mlb.com/api/v1/stats/leaders?{query}",opener=urlopen),count)
    ids=source._mlb_team_ids(target.year)
    # Same strictly-prior team games for both established production indices.
    ki=build_k_index(source._memo_team_season,ids,target)
    oi=build_outs_index(source._memo_team_season,ids,target)
    indexes={"PITCHER_K":ki,"PITCHER_OUTS":oi}

    def one(item):
        return per_pitcher(MLBGenericHistorySource(),item,target,indexes)

    results={}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(one,p):p for p in leaders}
        for future in as_completed(futures):
            item=futures[future]
            results[item["pitcher_id"]]=future.result()
    ordered=[results[p["pitcher_id"]] for p in leaders]
    eligible=[r for r in ordered if r["status"]=="EVALUATED"]
    if len(eligible)<MIN_PITCHERS:
        raise ValueError(f"Opponent-index coverage below locked minimum {len(eligible)}<{MIN_PITCHERS}")
    all_rows=[dict(row,pitcher_id=r["pitcher_id"]) for r in eligible for row in r["records"]]
    s=summarize(all_rows)
    return {
        "version":VERSION,
        "target_date":target.isoformat(),
        "cohort":"2025 MLB IP leader top 30, no 2026 performance selection",
        "cohort_sha256":canonical_json_sha256(leaders),
        "selected_count":len(leaders),
        "eligible_count":len(eligible),
        "model_changed":False,
        "prices_used":False,
        "postseason_adjusted":False,
        "promotion_allowed":False,
        "limitations":"2026 regular-season only, opponent indices K/outs; excludes lineup K and bullpen/workload context; half-line grid outcomes correlated",
        "aggregate":{"overall":s["overall"],"markets":s["markets"]},
        "pitchers":ordered,
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--target-date",default="2026-10-07")
    p.add_argument("--workers",type=int,default=6)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    result=run(date.fromisoformat(a.target_date),workers=a.workers)
    out=Path(a.output)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf8")
    print("OPPONENT_ADJUSTED_BASELINE_VS_PRIOR",json.dumps(result["aggregate"],sort_keys=True))
    print(f"EVALUATED {result['eligible_count']}/{result['selected_count']} pitchers")
    print("RESEARCH_ONLY_NOT_PROMOTED")


if __name__=="__main__":
    main()
