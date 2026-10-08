"""Fail-closed graded readout for prospective 2026 postseason pitcher K/outs.

Only complete, independently recorded *pregame* pitcher-game grids count.
Repeated K/outs prop thresholds belong to the same game cluster; never call
the number of scored thresholds the number of independent games.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime,timezone
from math import isfinite,log
from pathlib import Path
from random import Random
from statistics import mean
import json
from typing import Any,Mapping

from .mlb_postseason_k_outs_forward_shadow import (
    VERSION as PREDICTION_VERSION, MARKET_LINES, _sha
)

VERSION="mlb_postseason_2026_forward_research_readout_v1"
MIN_INDEPENDENT_GAMES=25
MIN_COMPLETE_STARTS=40
BOOTSTRAP_DRAWS=2000

class ShadowReadoutError(ValueError):
    pass

def _date(value: Any)->datetime:
    try: stamp=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except (TypeError,ValueError) as exc:raise ShadowReadoutError("INVALID_TIMESTAMP") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ShadowReadoutError("NAIVE_TIMESTAMP")
    return stamp.astimezone(timezone.utc)

def _read(path:Path)->dict[str,Any]:
    row=json.loads(path.read_text(encoding="utf8"))
    if not isinstance(row,dict):raise ShadowReadoutError("NOT_JSON_OBJECT")
    sha=row.get("receipt_sha256")
    if _sha({k:v for k,v in row.items() if k!="receipt_sha256"})!=sha:
        raise ShadowReadoutError("TAMPERED_RECEIPT:"+str(path))
    return row

def _identity(row:Mapping[str,Any])->tuple[int,int,str,float]:
    try: identity=(int(row["game_pk"]),int(row["pitcher_id"]),
                   str(row["market"]),float(row["line"]))
    except (KeyError,TypeError,ValueError) as exc:
        raise ShadowReadoutError("MISSING_IDENTITY") from exc
    if identity[2] not in MARKET_LINES or identity[3] not in MARKET_LINES[identity[2]]:
        raise ShadowReadoutError("UNREGISTERED_THRESHOLD")
    return identity

def _log_loss(y:int,p:float)->float:
    p=max(1e-9,min(1-1e-9,float(p)))
    return -y*log(p)-(1-y)*log(1-p)

def _summarize(rows:list[dict[str,Any]])->dict[str,Any]:
    if not rows:raise ShadowReadoutError("NO_GRADED_ROWS")
    return {
        "scored_thresholds_correlated":len(rows),
        "complete_pitcher_games":len(set((x["game_pk"],x["pitcher_id"]) for x in rows)),
        "independent_game_clusters":len(set(x["game_pk"] for x in rows)),
        "baseline_brier":mean(r["baseline_brier"] for r in rows),
        "shadow_brier":mean(r["shadow_brier"] for r in rows),
        "delta_brier":mean(r["shadow_brier"]-r["baseline_brier"] for r in rows),
        "baseline_log_loss":mean(r["baseline_log_loss"] for r in rows),
        "shadow_log_loss":mean(r["shadow_log_loss"] for r in rows),
        "delta_log_loss":mean(r["shadow_log_loss"]-r["baseline_log_loss"] for r in rows),
    }

def _integer_final_count(value:Any,market:str)->int:
    # bool is an int subclass; float/str must not be truncated or coerced.
    if isinstance(value,bool) or not isinstance(value,int):
        raise ShadowReadoutError("NONINTEGER_FINAL_COUNT")
    if value<0 or (market=="PITCHER_OUTS" and value>27):
        raise ShadowReadoutError("UNPHYSICAL_FINAL_COUNT")
    return value

def _recorded_brier(value:Any)->float:
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        raise ShadowReadoutError("MALFORMED_SETTLEMENT_BRIER")
    score=float(value)
    if not isfinite(score):
        raise ShadowReadoutError("NONFINITE_SETTLEMENT_BRIER")
    return score

def game_cluster_bootstrap(rows:list[dict[str,Any]],seed:int)->list[float]:
    """Resample games, then score the same threshold-weighted mean the readout reports.

    A mean of per-game means does not match delta_brier when a game contributes
    more thresholds (two starters, or a partial market grid). Cluster sums and
    counts keep that statistic and avoid rebuilding a mean() over every draw.
    """
    groups=defaultdict(list)
    for r in rows:
        groups[r["game_pk"]].append(r["shadow_brier"]-r["baseline_brier"])
    clusters=[(sum(groups[k]),len(groups[k])) for k in sorted(groups)]
    if len(clusters)<MIN_INDEPENDENT_GAMES:
        raise ShadowReadoutError("NOT_ENOUGH_INDEPENDENT_GAME_CLUSTERS")
    rng=Random(seed)
    n=len(clusters)
    draws=[]
    for _ in range(BOOTSTRAP_DRAWS):
        total=0.0
        count=0
        for _pick in range(n):
            cluster_sum,cluster_count=clusters[rng.randrange(n)]
            total+=cluster_sum
            count+=cluster_count
        draws.append(total/count)
    draws.sort()
    return [draws[int(.025*len(draws))],draws[int(.975*len(draws))]]

def readout(predictions_dir:Path,settlements_dir:Path)->dict[str,Any]:
    predictions={}
    for path in sorted(predictions_dir.glob("*.json")):
        row=_read(path)
        if row.get("schema")!=PREDICTION_VERSION or row.get("status")!="PREGAME_CAPTURED":
            raise ShadowReadoutError("INVALID_PREGAME_SCHEMA")
        if row.get("allow_betting_card") is not False or row.get("live_market_price_bound") is not False:
            raise ShadowReadoutError("UNAUTHORIZED_PREGAME_MARKET_CLAIM")
        if row.get("shadow_transfer_validated") is not False:
            raise ShadowReadoutError("UNPROVEN_SHADOW_CLAIM")
        if _date(row["captured_at_utc"])>=_date(row["scheduled_first_pitch_utc"]):
            raise ShadowReadoutError("BACKFILLED_PREGAME_RECEIPT")
        identity=_identity(row)
        if identity in predictions:raise ShadowReadoutError("DUPLICATE_PREDICTION")
        for name in ("baseline_opponent_adjusted_p_over","postseason_shadow_research_p_over"):
            p=float(row[name])
            if not isfinite(p) or not 0<=p<=1:raise ShadowReadoutError("BAD_PROBABILITY")
        predictions[identity]=row

    settlements={}
    for path in sorted(settlements_dir.glob("*.json")):
        loaded=json.loads(path.read_text(encoding="utf8"))
        if isinstance(loaded,dict) and loaded.get("status")=="GRADED":
            _recorded_brier(loaded.get("baseline_brier"))
            _recorded_brier(loaded.get("shadow_brier"))
        row=_read(path)
        if row.get("schema")!="mlb_postseason_k_outs_2026_shadow_settlement_v1":
            raise ShadowReadoutError("INVALID_SETTLEMENT_SCHEMA")
        identity=_identity(row)
        if identity not in predictions:raise ShadowReadoutError("SETTLEMENT_WITHOUT_PREGAME_RECEIPT")
        if identity in settlements:raise ShadowReadoutError("DUPLICATE_SETTLEMENT")
        if row.get("prediction_receipt_sha256")!=predictions[identity]["receipt_sha256"]:
            raise ShadowReadoutError("SETTLEMENT_PREGAME_HASH_MISMATCH")
        if row.get("allow_betting_card") is not False:
            raise ShadowReadoutError("UNAUTHORIZED_SETTLEMENT_CLAIM")
        if _date(row["settled_at_utc"])<=_date(predictions[identity]["scheduled_first_pitch_utc"]):
            raise ShadowReadoutError("FINAL_RECEIPT_BEFORE_SCHEDULED_START")
        if row.get("status") not in ("GRADED","VOID_NOT_ACTUAL_STARTER"):
            raise ShadowReadoutError("BAD_SETTLEMENT_STATUS")
        settlements[identity]=row

    by_start=defaultdict(dict)
    invalid_groups=set()
    settlement_counts={}
    graded_count=0
    for identity,pred in predictions.items():
        group=(identity[0],identity[1])
        settled=settlements.get(identity)
        if not settled or settled["status"]!="GRADED":
            invalid_groups.add(group)
            continue
        count=_integer_final_count(settled.get("actual_count"),identity[2])
        count_key=(identity[0],identity[1],identity[2])
        prior_count=settlement_counts.get(count_key)
        if prior_count is not None and prior_count!=count:
            raise ShadowReadoutError("CONTRADICTORY_SETTLEMENT_COUNT")
        settlement_counts[count_key]=count
        outcome=int(count>identity[3])
        if settled.get("actual_over") is not bool(outcome):
            raise ShadowReadoutError("FINAL_OUTCOME_MISMATCH")
        b=float(pred["baseline_opponent_adjusted_p_over"])
        c=float(pred["postseason_shadow_research_p_over"])
        bb=(b-outcome)**2; cc=(c-outcome)**2
        recorded_baseline=_recorded_brier(settled.get("baseline_brier"))
        recorded_shadow=_recorded_brier(settled.get("shadow_brier"))
        if abs(recorded_baseline-bb)>1e-9 or abs(recorded_shadow-cc)>1e-9:
            raise ShadowReadoutError("SETTLEMENT_SCORE_TAMPERING")
        graded_count+=1
        by_start[group][(identity[2],identity[3])]={
            "game_pk":identity[0],"pitcher_id":identity[1],"market":identity[2],
            "line":identity[3],"y":outcome,"baseline_brier":bb,"shadow_brier":cc,
            "baseline_log_loss":_log_loss(outcome,b),
            "shadow_log_loss":_log_loss(outcome,c),
        }

    wanted={(m,line) for m,lines in MARKET_LINES.items() for line in lines}
    complete=[]
    for k,parts in by_start.items():
        if k in invalid_groups or set(parts)!=wanted:continue
        complete.extend(parts[x] for x in sorted(wanted))
    complete_starts=len({(x["game_pk"],x["pitcher_id"]) for x in complete})
    independent_games=len({x["game_pk"] for x in complete})
    enough=complete_starts>=MIN_COMPLETE_STARTS and independent_games>=MIN_INDEPENDENT_GAMES
    out={
        "version":VERSION,"status":"RESEARCH_READOUT_AVAILABLE" if enough else "NOT_DUE_INSUFFICIENT_FORWARD_EVIDENCE",
        "authority":"RESEARCH_ONLY","model_deployment_allowed":False,
        "betting_card_eligible":False,
        "min_complete_pitcher_games":MIN_COMPLETE_STARTS,
        "min_independent_games":MIN_INDEPENDENT_GAMES,
        "predictions_captured":len(predictions),"settlements_captured":len(settlements),
        "thresholds_graded":graded_count,
        "void_or_unsettled_thresholds":len(predictions)-graded_count,
        "complete_pitcher_games":complete_starts,"independent_games":independent_games,
        "incomplete_pitcher_game_groups":len(set(by_start)|invalid_groups)-complete_starts,
        "limits":"Exploratory, not prospective promotion validation. Historical shadow intercept was derived from context-blind data and transferred to a different opponent/lineup-aware live model; outcomes with unavailable pregame evidence are not inferred.",
    }
    if enough:
        out["combined"]=_summarize(complete)
        out["per_market"]={market:_summarize([x for x in complete if x["market"]==market])
                           for market in sorted(MARKET_LINES)}
        out["game_cluster_descriptive_bootstrap_95_brier_delta"]=game_cluster_bootstrap(complete,seed=2026)
    return out
