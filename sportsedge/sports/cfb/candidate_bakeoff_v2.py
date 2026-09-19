"""CFB four-candidate bakeoff evaluator V2.

Repairs the null construction before the first evaluation: each deterministic
within-season paired-label shuffle refits and rescores every preregistered
candidate. Engineering selection only; zero betting/model authority.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence
import numpy as np

from .candidate_bakeoff import (
    CFBCandidateBakeoffError, FAMILIES, _candidate_eval, _diagnostics, _hash,
)
from .candidate_registry_v2 import EQUAL

def _permute_outer_season_labels(rows, outer, rng):
    perm=[dict(r) for r in rows]
    by_season={s:[i for i,r in enumerate(rows) if int(r["season"])==s] for s in outer}
    for _, idx in by_season.items():
        if not idx: continue
        order=rng.permutation(idx)
        labels=[(rows[j]["home_score"],rows[j]["away_score"]) for j in order]
        for j,(h,a) in zip(idx,labels):
            perm[j]["home_score"],perm[j]["away_score"]=h,a
    return perm

def evaluate_cfb_candidate_bakeoff_v2(rows: Sequence[Mapping[str,Any]], config: Mapping[str,Any], *, input_identity: Mapping[str,Any]) -> dict[str,Any]:
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
    rng=np.random.default_rng(seed); null_max=[]
    for _ in range(shuffles):
        perm=_permute_outer_season_labels(data,outer,rng)
        null_scores={}
        for fam in FAMILIES:
            score,_,_=_candidate_eval(perm,fam,outer,grid)
            null_scores[fam]=score["selection_metric"]
        null_max.append(max(null_scores[EQUAL]-null_scores[f] for f in FAMILIES if f!=EQUAL))
    null_sorted=sorted(null_max); q=float(config["null"]["percentile"])
    threshold=float(null_sorted[int(np.ceil(q*(len(null_sorted)-1)))])
    challengers={}
    for fam in FAMILIES[1:]:
        imp=improvements[fam]; exceed=sum(x>=imp for x in null_max); p=(exceed+1)/(len(null_max)+1)
        challengers[fam]={"observed_improvement_vs_baseline":imp,"null_threshold":threshold,
                          "family_wise_p_value":p,"clears_null_threshold":bool(imp>threshold)}
    clearing=[f for f in FAMILIES[1:] if challengers[f]["clears_null_threshold"]]
    winner=min(clearing,key=lambda f:(observed[f]["selection_metric"],FAMILIES.index(f))) if clearing else None
    status="WINNER_SELECTED_FOR_FREEZE" if winner else "NO_CANDIDATE_DEMONSTRATED_SIGNAL_AT_THIS_SAMPLE"
    regulation=sum(1 for r in data if "regulation_home_score" in r and "regulation_away_score" in r)
    ot=sum(1 for r in data if "regulation_home_score" in r and "regulation_away_score" in r and
           r.get("regulation_home_score")==r.get("regulation_away_score") and r.get("home_score")!=r.get("away_score"))
    result={"schema":"CFB_CANDIDATE_BAKEOFF_RESULT_V2","status":status,"winner":winner,
            "input_identity":dict(input_identity),"rows_sha256":_hash(data),"observed":observed,
            "challengers":challengers,"null":{"threshold":threshold,"shuffle_count":shuffles,"seed":seed,
            "family_wise_max":True,"strict_exceedance":True,"refit_and_rescore_every_candidate_each_shuffle":True},
            "diagnostics":{f:_diagnostics(*preds[f]) for f in FAMILIES},
            "regulation_score_coverage":{"rows_with_regulation_scores":regulation,"rows_total":len(data)},
            "overtime_games_in_profile":ot,
            "authority":{"model_p_created":False,"truth_gate_authority":False,"promotion_authority":False,
                         "eligibility_changed":False,"staking_authority":False,"evidence_clock_authority":False,
                         "backfill":False,"official_authority":False}}
    result["result_sha256"]=_hash(result)
    return result

__all__=["evaluate_cfb_candidate_bakeoff_v2"]
