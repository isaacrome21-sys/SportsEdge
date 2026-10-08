#!/usr/bin/env python3
"""2026 forward-season pitcher window bakeoff on a pre-selected 2025 cohort.

Sample definition is locked BEFORE reviewing 2026 outcomes:
the top 30 2025 regular-season MLB innings-pitched leaders from StatsAPI.
Evaluate only strictly-prior 2026 regular-season starts; price-blind, research
only. Missing/invalid leader identity or fetch failures fail closed. No change
to production model or its governed card.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode

from sportsedge.mlb_generic_features import MLBGenericHistorySource, _read_json
from sportsedge.source_lineage import canonical_json_sha256
from scripts.eval_mlb_pitcher_window_blend import evaluate, pitcher_starts, summarize

COHORT_SEASON = 2025
TEST_SEASON = 2026
COHORT_SIZE = 30
MIN_HELDOUT_GAMES = 5
MIN_ELIGIBLE_PITCHERS = 8
VERSION = "mlb_pitcher_2025_ip_leaders_2026_holdout_v1"


def select_2025_leaders(payload: Mapping[str,Any], count: int = COHORT_SIZE) -> list[dict[str,Any]]:
    if not isinstance(payload, Mapping):
        raise ValueError("MLB leader payload must be a mapping")
    groups=payload.get("leagueLeaders")
    if not isinstance(groups,list) or not groups:
        raise ValueError("MLB leader payload missing leagueLeaders")
    matches=[g for g in groups if g.get("leaderCategory") == "inningsPitched"]
    if len(matches)!=1:
        raise ValueError("Exactly one inningsPitched leader group required")
    leaders=matches[0].get("leaders")
    if not isinstance(leaders,list) or len(leaders)<count:
        raise ValueError("Insufficient pre-declared 2025 innings leaders")
    out=[]
    ids=set()
    for item in leaders[:count]:
        person=item.get("person") or {}
        pid=person.get("id")
        if not isinstance(pid,int) or pid<=0 or pid in ids:
            raise ValueError("Invalid or duplicated pre-2026 leader ID")
        ids.add(pid)
        name=str(person.get("fullName") or person.get("lastFirstName") or "").strip()
        if not name:
            raise ValueError("Missing pre-2026 leader display name")
        out.append({"pitcher_id":pid,"name":name,"2025_ip_rank":len(out)+1})
    return out


def restrict_2026_evaluations(evaluation: Mapping[str,Any], cutoff_date: str) -> dict[str,Any]:
    rows=[r for r in evaluation["records"] if cutoff_date <= r["date"][:10] and r["date"][:4] == str(TEST_SEASON)]
    if not rows:
        return {"records":[],"overall":None,"markets":{}}
    return summarize(rows)


def run(target_date: date, *, cohort_size: int = COHORT_SIZE, workers: int = 5) -> dict[str,Any]:
    if target_date.year != TEST_SEASON:
        raise ValueError("Expected an explicitly frozen 2026 holdout target")
    query=urlencode({"leaderCategories":"inningsPitched","statGroup":"pitching",
                     "season":COHORT_SEASON,"sportId":1,"gameType":"R","limit":cohort_size})
    raw=_read_json(f"https://statsapi.mlb.com/api/v1/stats/leaders?{query}")
    leaders=select_2025_leaders(raw,cohort_size)
    identity=canonical_json_sha256({"selection_rule":"2025_IP_LEADERS",
                                    "season":COHORT_SEASON,"pitchers":leaders})
    cutoff=f"{TEST_SEASON}-01-01"

    def one(item: dict[str,Any]) -> dict[str,Any]:
        source=MLBGenericHistorySource()
        starts=pitcher_starts(source,item["pitcher_id"],target_date)
        if len(starts)<16:
            return {**item,"status":"INSUFFICIENT_ALL_SEASON_STARTS",
                    "available_starts":len(starts),"holdout_games":0}
        evaluated=evaluate(starts)
        h=restrict_2026_evaluations(evaluated,cutoff)
        games=h["overall"]["unique_heldout_dates"] if h["overall"] else 0
        if games<MIN_HELDOUT_GAMES:
            return {**item,"status":"INSUFFICIENT_2026_HOLDOUTS",
                    "available_starts":len(starts),"holdout_games":games}
        return {**item,"status":"EVALUATED",
                "available_starts":len(starts),
                "holdout_games":games,
                "overall":h["overall"],"markets":h["markets"],"records":h["records"]}

    results={}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(one,p):p for p in leaders}
        for future in as_completed(futures):
            expected=futures[future]
            # Fail closed on transient source errors rather than silently
            # cherry-picking only reachable pitcher IDs.
            results[expected["pitcher_id"]]=future.result()
    ordered=[results[p["pitcher_id"]] for p in leaders]
    eligible=[r for r in ordered if r["status"]=="EVALUATED"]
    if len(eligible)<MIN_ELIGIBLE_PITCHERS:
        raise ValueError(f"Broad cohort not evaluable: {len(eligible)}<{MIN_ELIGIBLE_PITCHERS}")
    records=[{**row,"pitcher_id":r["pitcher_id"],"pitcher":r["name"]}
             for r in eligible for row in r["records"]]
    aggregate=summarize(records)
    return {
        "version":VERSION,"cohort_source":"MLB_STATSAPI_2025_INNINGS_PITCHED_LEADERS",
        "cohort_source_sha256":identity, "cohort_order":leaders,
        "cohort_size":cohort_size, "eligible_pitchers":len(eligible),
        "test_season":TEST_SEASON, "target_date":target_date.isoformat(),
        "strictly_prior_regular_season_only":True,
        "market_prices_used_for_fitting":False,
        "official":False,"promotion_allowed":False,"production_model_modified":False,
        "limitation":"2025 leaderboard-selected 2026 holdout; context-blind marginals and correlated lines; no postseason workload calibration",
        "aggregate":{"overall":aggregate["overall"],"markets":aggregate["markets"]},
        "pitchers":ordered,
    }


def main()->None:
    p=argparse.ArgumentParser()
    p.add_argument("--target-date",default="2026-10-07")
    p.add_argument("--cohort-size",type=int,default=COHORT_SIZE)
    p.add_argument("--workers",type=int,default=5)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    result=run(date.fromisoformat(args.target_date),cohort_size=args.cohort_size,workers=args.workers)
    out=Path(args.output)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print("2026_FORWARDFOLD_PITCHER_BAKEOFF",json.dumps(result["aggregate"]["overall"]))
    print(f"ELIGIBLE_PITCHERS {result['eligible_pitchers']} / {result['cohort_size']}")
    print("DO_NOT_PROMOTE_UNVALIDATED_MODEL")

if __name__=="__main__":
    main()
