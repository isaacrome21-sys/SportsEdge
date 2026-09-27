"""Frozen CFB four-candidate bakeoff evaluator.

Engineering selection only. This module creates no Model_P, Truth Gate, promotion,
eligibility, staking, evidence-clock, backfill, or OFFICIAL authority.
"""
from __future__ import annotations

from hashlib import sha256
import json
from math import sqrt
from typing import Any, Mapping, Sequence

import numpy as np

from .candidate_model_v2 import fit_cfb_candidate_score_model
from .candidate_registry_v2 import EQUAL, RELIABILITY, BLEND, GAMES

FAMILIES=(EQUAL, RELIABILITY, BLEND, GAMES)

class CFBCandidateBakeoffError(ValueError):
    pass

def _canon(v: Any) -> bytes:
    return json.dumps(v,sort_keys=True,separators=(",",":"),allow_nan=False).encode()

def _hash(v: Any) -> str:
    return sha256(_canon(v)).hexdigest()

def _rmse(pred: Sequence[tuple[float,float]], rows: Sequence[Mapping[str,Any]]) -> float:
    if len(pred)!=len(rows) or not rows:
        raise CFBCandidateBakeoffError("CFB_BAKEOFF_SCORE_ROWS_INVALID")
    s=0.0
    for (ph,pa),r in zip(pred,rows):
        s+=(ph-float(r["home_score"]))**2+(pa-float(r["away_score"]))**2
    return sqrt(s/(2*len(rows)))

def _fit_score(train, valid, family, alpha):
    m=fit_cfb_candidate_score_model(train,family=family,ridge_alpha=alpha)
    return _rmse([m.predict_means(r) for r in valid],valid)

def _choose_alpha(rows, family, grid, outer_season):
    prior=sorted({int(r["season"]) for r in rows if int(r["season"])<outer_season})
    inner=[s for s in prior if len([p for p in prior if p<s])>=2]
    if not inner:
        raise CFBCandidateBakeoffError(f"CFB_BAKEOFF_INNER_FOLDS_INSUFFICIENT:{outer_season}")
    scored=[]
    for a in grid:
        vals=[]
        for s in inner:
            tr=[r for r in rows if int(r["season"])<s]
            va=[r for r in rows if int(r["season"])==s]
            if len(tr)>=20 and va:
                vals.append(_fit_score(tr,va,family,float(a)))
        if not vals:
            raise CFBCandidateBakeoffError(f"CFB_BAKEOFF_INNER_FOLD_EMPTY:{outer_season}")
        scored.append((sum(vals)/len(vals),float(a)))
    return min(scored,key=lambda x:(x[0],x[1]))[1]

def _candidate_eval(rows, family, outer, grid):
    folds=[]
    all_pred=[]; all_rows=[]
    for season in outer:
        tr=[r for r in rows if int(r["season"])<season]
        va=[r for r in rows if int(r["season"])==season]
        if len(tr)<20 or not va:
            raise CFBCandidateBakeoffError(f"CFB_BAKEOFF_OUTER_FOLD_EMPTY:{season}")
        alpha=_choose_alpha(rows,family,grid,season)
        model=fit_cfb_candidate_score_model(tr,family=family,ridge_alpha=alpha)
        pred=[model.predict_means(r) for r in va]
        folds.append({"season":season,"rows":len(va),"alpha":alpha,"rmse":_rmse(pred,va),
                      "alpha_at_grid_boundary":alpha in (float(grid[0]),float(grid[-1]))})
        all_pred.extend(pred); all_rows.extend(va)
    return {"selection_metric":_rmse(all_pred,all_rows),"folds":folds},all_pred,all_rows

def _diagnostics(pred, rows):
    margins=[h-a for h,a in pred]; totals=[h+a for h,a in pred]
    real_m=[float(r["home_score"])-float(r["away_score"]) for r in rows]
    real_t=[float(r["home_score"])+float(r["away_score"]) for r in rows]
    def rr(a,b): return sqrt(sum((x-y)**2 for x,y in zip(a,b))/len(a))
    def mass(xs,k): return sum(abs(round(x))==k for x in xs)/len(xs)
    return {"margin_rmse":rr(margins,real_m),"total_rmse":rr(totals,real_t),
            "absolute_margin_mass_at_3":{"predicted":mass(margins,3),"realized":mass(real_m,3)},
            "absolute_margin_mass_at_7":{"predicted":mass(margins,7),"realized":mass(real_m,7)}}

def evaluate_cfb_candidate_bakeoff(rows: Sequence[Mapping[str,Any]], config: Mapping[str,Any],
                                   *, input_identity: Mapping[str,Any]) -> dict[str,Any]:
    data=[dict(r) for r in rows]
    if not data: raise CFBCandidateBakeoffError("CFB_BAKEOFF_ROWS_EMPTY")
    outer=[int(x) for x in config["outer_validation_seasons"]]
    grid=[float(x) for x in config["ridge_alpha_grid"]]
    if tuple(config.get("candidate_families") or ())!=FAMILIES:
        raise CFBCandidateBakeoffError("CFB_BAKEOFF_FAMILY_ORDER_DRIFT")
    observed={}; preds={}
    for fam in FAMILIES:
        score,pred,scored_rows=_candidate_eval(data,fam,outer,grid)
        observed[fam]=score; preds[fam]=(pred,scored_rows)
    base=observed[EQUAL]["selection_metric"]
    improvements={f:base-observed[f]["selection_metric"] for f in FAMILIES if f!=EQUAL}

    shuffles=int(config["null"]["shuffle_count"]); seed=int(config["null"]["seed"])
    rng=np.random.default_rng(seed)
    null_max=[]
    # Frozen null: within each outer validation season, permute paired score labels
    # across validation feature rows. Candidate predictions remain those fit without
    # the held-out season, preserving the temporal training boundary.
    byfam={f:preds[f][0] for f in FAMILIES}
    scored=preds[EQUAL][1]
    season_indices={s:[i for i,r in enumerate(scored) if int(r["season"])==s] for s in outer}
    for _ in range(shuffles):
        perm=[dict(r) for r in scored]
        for s,idx in season_indices.items():
            order=rng.permutation(idx)
            labels=[(scored[j]["home_score"],scored[j]["away_score"]) for j in order]
            for j,(h,a) in zip(idx,labels):
                perm[j]["home_score"],perm[j]["away_score"]=h,a
        rms={f:_rmse(byfam[f],perm) for f in FAMILIES}
        null_max.append(max(rms[EQUAL]-rms[f] for f in FAMILIES if f!=EQUAL))
    null_sorted=sorted(null_max)
    q=float(config["null"]["percentile"])
    # NumPy method='higher': ceil(q*(n-1)) order statistic.
    threshold=float(null_sorted[int(np.ceil(q*(len(null_sorted)-1)))])
    challengers={}
    for fam in FAMILIES[1:]:
        imp=improvements[fam]
        exceed=sum(x>=imp for x in null_max)
        p=(exceed+1)/(len(null_max)+1)
        challengers[fam]={"observed_improvement_vs_baseline":imp,"null_threshold":threshold,
                          "family_wise_p_value":p,"clears_null_threshold":bool(imp>threshold)}
    clearing=[f for f in FAMILIES[1:] if challengers[f]["clears_null_threshold"]]
    winner=min(clearing,key=lambda f:(observed[f]["selection_metric"],FAMILIES.index(f))) if clearing else None
    status="WINNER_SELECTED_FOR_FREEZE" if winner else "NO_CANDIDATE_DEMONSTRATED_SIGNAL_AT_THIS_SAMPLE"
    regulation=sum(1 for r in data if "regulation_home_score" in r and "regulation_away_score" in r)
    ot=sum(1 for r in data if r.get("regulation_home_score")==r.get("regulation_away_score") and
           r.get("home_score")!=r.get("away_score") and "regulation_home_score" in r)
    result={"schema":"CFB_CANDIDATE_BAKEOFF_RESULT_V1","status":status,"winner":winner,
            "input_identity":dict(input_identity),"rows_sha256":_hash(data),
            "observed":observed,"challengers":challengers,"null":{"threshold":threshold,
            "shuffle_count":shuffles,"seed":seed,"family_wise_max":True,"strict_exceedance":True},
            "diagnostics":{f:_diagnostics(*preds[f]) for f in FAMILIES},
            "regulation_score_coverage":{"rows_with_regulation_scores":regulation,"rows_total":len(data)},
            "overtime_games_in_profile":ot,
            "authority":{"model_p_created":False,"truth_gate_authority":False,"promotion_authority":False,
                         "eligibility_changed":False,"staking_authority":False,"evidence_clock_authority":False,
                         "backfill":False,"official_authority":False}}
    result["result_sha256"]=_hash(result)
    return result

__all__=["CFBCandidateBakeoffError","FAMILIES","evaluate_cfb_candidate_bakeoff"]
