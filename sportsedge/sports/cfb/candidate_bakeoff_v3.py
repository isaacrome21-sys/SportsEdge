"""CFB bakeoff V3: V2-identical public result plus observed-pass capture."""
from __future__ import annotations
from typing import Any, Mapping, Sequence
import numpy as np

from .candidate_bakeoff import (
    CFBCandidateBakeoffError, FAMILIES, _candidate_eval, _choose_alpha,
    _diagnostics, _hash, _rmse,
)
from .candidate_bakeoff_v2 import _permute_outer_season_labels
from .candidate_model_v2 import fit_cfb_candidate_score_model
from .candidate_registry_v2 import EQUAL

CAPTURE_FAMILIES=FAMILIES[1:]

def _id(r):
    try: return {"season":int(r["season"]),"week":int(r["week"]),"game_id":str(r["game_id"])}
    except (KeyError,TypeError,ValueError) as exc:
        raise CFBCandidateBakeoffError("CFB_BAKEOFF_V3_CAPTURE_ROW_IDENTITY_REQUIRED") from exc

def _observed_eval(rows,family,outer,grid):
    folds=[]; all_pred=[]; all_rows=[]; captured=[]
    for season in outer:
        tr=[r for r in rows if int(r["season"])<season]
        va=[r for r in rows if int(r["season"])==season]
        if len(tr)<20 or not va: raise CFBCandidateBakeoffError(f"CFB_BAKEOFF_OUTER_FOLD_EMPTY:{season}")
        alpha=_choose_alpha(rows,family,grid,season)
        model=fit_cfb_candidate_score_model(tr,family=family,ridge_alpha=alpha)
        pred=[model.predict_means(r) for r in va]
        tpred=[model.predict_means(r) for r in tr]
        folds.append({"season":season,"rows":len(va),"alpha":alpha,"rmse":_rmse(pred,va),
                      "alpha_at_grid_boundary":alpha in (float(grid[0]),float(grid[-1]))})
        op=[]
        for (ph,pa),r in zip(pred,va):
            x=_id(r); x.update(predicted_home_score=float(ph),predicted_away_score=float(pa),
                               realized_home_score=float(r["home_score"]),realized_away_score=float(r["away_score"])); op.append(x)
        resid=[]
        for (ph,pa),r in zip(tpred,tr):
            x=_id(r); x.update(home_residual=float(r["home_score"])-float(ph),away_residual=float(r["away_score"])-float(pa)); resid.append(x)
        captured.append({"outer_season":int(season),"frozen_alpha":float(alpha),
                         "outer_predictions":op,"training_residuals":resid})
        all_pred.extend(pred); all_rows.extend(va)
    return {"selection_metric":_rmse(all_pred,all_rows),"folds":folds},all_pred,all_rows,{"family":family,"folds":captured}

def evaluate_cfb_candidate_bakeoff_v3(rows:Sequence[Mapping[str,Any]],config:Mapping[str,Any],*,input_identity:Mapping[str,Any]):
    data=[dict(r) for r in rows]
    if not data: raise CFBCandidateBakeoffError("CFB_BAKEOFF_ROWS_EMPTY")
    outer=[int(x) for x in config["outer_validation_seasons"]]; grid=[float(x) for x in config["ridge_alpha_grid"]]
    if tuple(config.get("candidate_families") or ())!=FAMILIES: raise CFBCandidateBakeoffError("CFB_BAKEOFF_FAMILY_ORDER_DRIFT")
    observed={}; preds={}; captures={}
    for fam in FAMILIES:
        score,pred,scored,cap=_observed_eval(data,fam,outer,grid)
        observed[fam]=score; preds[fam]=(pred,scored)
        if fam in CAPTURE_FAMILIES: captures[fam]=cap
    base=observed[EQUAL]["selection_metric"]
    improvements={f:base-observed[f]["selection_metric"] for f in FAMILIES if f!=EQUAL}
    shuffles=int(config["null"]["shuffle_count"]); seed=int(config["null"]["seed"]); rng=np.random.default_rng(seed); null_max=[]
    for _ in range(shuffles):
        perm=_permute_outer_season_labels(data,outer,rng); scores={}
        for fam in FAMILIES:
            score,_,_=_candidate_eval(perm,fam,outer,grid); scores[fam]=score["selection_metric"]
        null_max.append(max(scores[EQUAL]-scores[f] for f in FAMILIES if f!=EQUAL))
    ordered=sorted(null_max); q=float(config["null"]["percentile"]); threshold=float(ordered[int(np.ceil(q*(len(ordered)-1)))])
    challengers={}
    for fam in FAMILIES[1:]:
        imp=improvements[fam]; exceed=sum(x>=imp for x in null_max); p=(exceed+1)/(len(null_max)+1)
        challengers[fam]={"observed_improvement_vs_baseline":imp,"null_threshold":threshold,"family_wise_p_value":p,"clears_null_threshold":bool(imp>threshold)}
    clearing=[f for f in FAMILIES[1:] if challengers[f]["clears_null_threshold"]]
    winner=min(clearing,key=lambda f:(observed[f]["selection_metric"],FAMILIES.index(f))) if clearing else None
    status="WINNER_SELECTED_FOR_FREEZE" if winner else "NO_CANDIDATE_DEMONSTRATED_SIGNAL_AT_THIS_SAMPLE"
    regulation=sum(1 for r in data if "regulation_home_score" in r and "regulation_away_score" in r)
    ot=sum(1 for r in data if "regulation_home_score" in r and "regulation_away_score" in r and r.get("regulation_home_score")==r.get("regulation_away_score") and r.get("home_score")!=r.get("away_score"))
    result={"schema":"CFB_CANDIDATE_BAKEOFF_RESULT_V2","status":status,"winner":winner,
            "input_identity":dict(input_identity),"rows_sha256":_hash(data),"observed":observed,"challengers":challengers,
            "null":{"threshold":threshold,"shuffle_count":shuffles,"seed":seed,"family_wise_max":True,"strict_exceedance":True,"refit_and_rescore_every_candidate_each_shuffle":True},
            "diagnostics":{f:_diagnostics(*preds[f]) for f in FAMILIES},
            "regulation_score_coverage":{"rows_with_regulation_scores":regulation,"rows_total":len(data)},"overtime_games_in_profile":ot,
            "authority":{"model_p_created":False,"truth_gate_authority":False,"promotion_authority":False,"eligibility_changed":False,"staking_authority":False,"evidence_clock_authority":False,"backfill":False,"official_authority":False}}
    result["result_sha256"]=_hash(result)
    capture={"schema":"CFB_CANDIDATE_BAKEOFF_PRIVATE_CAPTURE_V1","status":"WINNER_CAPTURE_RETAINED" if winner else "NO_WINNER_NO_CAPTURE_RETAINED",
             "capture_pass":"OBSERVED_UNPERMUTED_ONLY","captured_families_during_run":list(CAPTURE_FAMILIES),
             "retained_family":winner,"winner_capture":captures.get(winner) if winner else None,
             "authority":{k:False for k in result["authority"]}}
    capture["capture_sha256"]=_hash(capture)
    return result,capture

__all__=["CAPTURE_FAMILIES","evaluate_cfb_candidate_bakeoff_v3"]
