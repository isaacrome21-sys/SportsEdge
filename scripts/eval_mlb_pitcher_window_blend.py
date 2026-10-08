#!/usr/bin/env python3
"""Strictly chronological pitcher-prop prior-window bakeoff (research only).

Compare a 10-start unadjusted marginal against a candidate that blends the
non-overlapping 11-30-start prior capped at the recent effective sample size.
Neither candidate is the context-adjusted production prop model. Every evaluated
start is strictly later than every training start; sportsbook prices are not
used. This does not validate postseason workload or authorize card promotion.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from math import log
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

from sportsedge.mlb_generic_features import MLBGenericHistorySource, _number
from sportsedge.mlb_joint_features import _pitcher_pool
from sportsedge.pitcher_joint_engine import _price_values, _value

VERSION = "mlb_pitcher_all_market_window_bakeoff_v1"
MARKET_LINES = {
    "PITCHER_OUTS": (12.5, 15.5, 17.5),
    "PITCHER_K": (2.5, 4.5, 5.5),
    "PITCHER_ER": (1.5, 2.5),
    "PITCHER_HITS_ALLOWED": (3.5, 4.5),
    "PITCHER_BB": (1.5, 2.5),
    "PITCHER_HITS_WALKS_ER": (7.5, 9.5),
}
MIN_OLDER = 5
RECENT_WINDOW = 10
PRIOR_WINDOW = 20


def pitcher_starts(source: MLBGenericHistorySource, player_id: int, target_date: date) -> list[dict[str, Any]]:
    rows = source.player_rows(player_id=player_id, group="pitching", target_date=target_date)
    eligible = [r for r in rows if _number(r["stat"].get("gamesStarted", 0), "gamesStarted") >= 1]
    return [
        {"date": r["date"].isoformat(), "row": normalized}
        for r, normalized in zip(eligible, _pitcher_pool(eligible))
    ]


def marginal(pool: Sequence[Mapping[str, int]], market: str, line: float,
             *, older: Sequence[Mapping[str, int]] | None = None) -> float:
    values = [_value(row, market) for row in pool]
    weights = [1 / len(pool)] * len(pool)
    prior_vals = [_value(row, market) for row in older] if older else None
    prior_weights = [1 / len(older)] * len(older) if older else None
    p, push, _meta = _price_values(
        values, weights, float(line), "OVER", market,
        prior_values=prior_vals, prior_weights=prior_weights,
    )
    if push:
        raise ValueError("Half-line bakeoff should never push")
    return p


def evaluate(starts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Each heldout row is scored only with starts dated strictly earlier."""
    history = list(starts)
    if any(history[i]["date"] > history[i+1]["date"] for i in range(len(history)-1)):
        raise ValueError("Starts must be chronologically sorted")
    if any(not isinstance(item.get("row"), Mapping) for item in history):
        raise ValueError("Missing pitcher joint row")
    records = []
    for idx in range(RECENT_WINDOW + MIN_OLDER, len(history)):
        heldout = history[idx]
        older_training = history[:idx]
        # Game-date precision cannot order doubleheaders within a day.
        if any(x["date"] >= heldout["date"] for x in older_training):
            continue
        recent = [x["row"] for x in older_training[-RECENT_WINDOW:]]
        older = [x["row"] for x in older_training[-(RECENT_WINDOW+PRIOR_WINDOW):-RECENT_WINDOW]]
        if len(older) < MIN_OLDER:
            continue
        for market, lines in MARKET_LINES.items():
            for line in lines:
                baseline = marginal(recent, market, line)
                candidate = marginal(recent, market, line, older=older)
                actual = float(_value(heldout["row"], market) > line)
                records.append({
                    "date": heldout["date"], "market": market, "line": line,
                    "actual_over": actual, "p_recent_only": baseline,
                    "p_recent_plus_capped_prior": candidate,
                    "recent_start_count": len(recent),
                    "older_nonoverlap_start_count": len(older),
                    "training_last_date": older_training[-1]["date"],
                })
    if not records:
        raise ValueError("Not enough strict-prior starts for evaluation")
    return summarize(records)


def summarize(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    def metric(items: Sequence[Mapping[str, Any]], key: str) -> dict[str, float]:
        probs = [float(row[key]) for row in items]
        actual = [float(row["actual_over"]) for row in items]
        n = len(probs)
        return {
            "brier": sum((p-y)**2 for p,y in zip(probs,actual))/n,
            "log_loss": sum(-y*log(max(1e-9,min(1-1e-9,p))) -
                            (1-y)*log(max(1e-9,min(1-1e-9,1-p)))
                            for p,y in zip(probs,actual))/n,
        }

    def pair(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        b=metric(items,"p_recent_only")
        c=metric(items,"p_recent_plus_capped_prior")
        return {
            "scored_rows":len(items),
            "unique_heldout_dates":len(set(r["date"] for r in items)),
            "baseline_recent_only":b,
            "candidate_recent_plus_capped_prior":c,
            "candidate_minus_baseline_brier":c["brier"]-b["brier"],
            "candidate_minus_baseline_log_loss":c["log_loss"]-b["log_loss"],
            "candidate_beats_baseline_brier":c["brier"]<b["brier"],
        }
    by_market = {}
    for market in MARKET_LINES:
        items = [r for r in records if r["market"] == market]
        if items:
            by_market[market] = pair(items)
    return {"overall":pair(records), "markets":by_market, "records":list(records)}


def run(*, pitchers: Mapping[str, int], target_date: date) -> dict[str, Any]:
    source=MLBGenericHistorySource()
    per_pitcher = {}
    all_rows=[]
    for name, pid in pitchers.items():
        starts = pitcher_starts(source,int(pid),target_date)
        result = evaluate(starts)
        per_pitcher[name] = {
            "player_id":int(pid), "total_prior_starts":len(starts),
            "overall":result["overall"], "markets":result["markets"],
            "evaluations":result["records"],
        }
        for row in result["records"]:
            all_rows.append(dict(row,pitcher=name))
    aggregate=summarize(all_rows)
    return {
        "version":VERSION, "target_date":target_date.isoformat(),
        "source":"MLB_STATSAPI_STRICT_PRIOR_REGULAR_SEASON_GAMELOG",
        "model_probabilities_changed":False,
        "postseason_workload_validated":False,
        "official":False,
        "promotion_allowed":False,
        "research_only":True,
        "comparison":"context-blind marginal ablation; not full live-game pricing",
        "fixed_window_spec":{"recent":RECENT_WINDOW,"older":PRIOR_WINDOW,"min_older":MIN_OLDER,"posterior":"Jeffreys settlement shrinkage"},
        "aggregate":{"overall":aggregate["overall"],"markets":aggregate["markets"]},
        "pitchers":per_pitcher,
    }


def main() -> None:
    p=argparse.ArgumentParser()
    p.add_argument("--target-date",default="2026-10-07")
    p.add_argument("--output",required=True)
    args=p.parse_args()
    payload=run(pitchers={"Nick Martinez":607259,"Max Fried":608331},
                target_date=date.fromisoformat(args.target_date))
    output=Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf8")
    print("PITCHER_WINDOW_BAKEOFF",json.dumps(payload["aggregate"],sort_keys=True))
    print("RESEARCH_ONLY_NOT_PROMOTED")

if __name__ == "__main__":
    main()
