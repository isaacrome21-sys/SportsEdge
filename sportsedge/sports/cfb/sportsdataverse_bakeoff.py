"""Frozen-style temporal evaluator for native SportsDataverse CFB candidates.

Engineering selection only. It creates no Model_P, promotion, staking, Truth Gate,
evidence-clock, backfill, or OFFICIAL authority.
"""
from __future__ import annotations
from math import sqrt
from typing import Any,Mapping,Sequence
from .sportsdataverse_candidate_model import FAMILIES,fit_native_score_model
from .sportsdataverse_weather import require_complete_weather

class SDVNativeBakeoffError(ValueError): pass

def _rmse(pred,rows):
 if len(pred)!=len(rows) or not rows: raise SDVNativeBakeoffError("CFB_SDV_BAKEOFF_SCORE_ROWS_INVALID")
 return sqrt(sum((h-float(r["home_points"]))**2+(a-float(r["away_points"]))**2 for (h,a),r in zip(pred,rows))/(2*len(rows)))

def _constants(config,family):
 c=config["candidates"].get(family)
 if not isinstance(c,Mapping): raise SDVNativeBakeoffError("CFB_SDV_CANDIDATE_CONFIG_MISSING:"+family)
 return dict(c.get("constants") or {})

def _fit_score(train,valid,family,alpha,constants):
 m=fit_native_score_model(train,family=family,ridge_alpha=alpha,constants=constants)
 return _rmse([m.predict_means(r,constants) for r in valid],valid)

def _choose_alpha(rows,family,grid,outer_season,constants):
 prior=sorted({int(r["season"]) for r in rows if int(r["season"])<outer_season})
 inner=[s for s in prior if len([p for p in prior if p<s])>=2]
 if not inner: raise SDVNativeBakeoffError(f"CFB_SDV_INNER_FOLDS_INSUFFICIENT:{outer_season}")
 scored=[]
 for alpha in grid:
  vals=[]
  for season in inner:
   tr=[r for r in rows if int(r["season"])<season]
   va=[r for r in rows if int(r["season"])==season]
   if len(tr)>=20 and va: vals.append(_fit_score(tr,va,family,float(alpha),constants))
  if not vals: raise SDVNativeBakeoffError(f"CFB_SDV_INNER_FOLD_EMPTY:{outer_season}")
  scored.append((sum(vals)/len(vals),float(alpha)))
 return min(scored,key=lambda x:(x[0],x[1]))[1]

def evaluate_native_candidates(rows:Sequence[Mapping[str,Any]],config:Mapping[str,Any])->dict[str,Any]:
 policy=config.get("candidate_selection_policy") or {}
 if policy.get("metric")!="JOINT_HOME_AWAY_SCORE_RMSE" or policy.get("tie_break")!="LOWEST_RMSE_THEN_FROZEN_FAMILY_ORDER" or list(policy.get("family_order") or [])!=list(FAMILIES) or policy.get("post_result_override_allowed") is not False:
  raise SDVNativeBakeoffError("CFB_SDV_CANDIDATE_SELECTION_POLICY_MISMATCH")
 data=[dict(r) for r in rows]
 if not data: raise SDVNativeBakeoffError("CFB_SDV_BAKEOFF_ROWS_EMPTY")
 if any(int(r["season"])>=2026 for r in data): raise SDVNativeBakeoffError("CFB_SDV_2026_OUTCOMES_PROHIBITED")
 require_complete_weather(data)
 hp=config["hyperparameter_policy"]; grid=[float(x) for x in hp["ridge_alpha_grid"]]
 seasons=sorted({int(r["season"]) for r in data})
 # Need at least three earlier seasons so nested alpha selection is genuinely temporal.
 outer=[s for s in seasons if len([p for p in seasons if p<s])>=3]
 if not outer: raise SDVNativeBakeoffError("CFB_SDV_OUTER_FOLDS_INSUFFICIENT")
 observed={}
 for family in FAMILIES:
  constants=_constants(config,family); folds=[]; all_pred=[]; all_rows=[]
  for season in outer:
   tr=[r for r in data if int(r["season"])<season]; va=[r for r in data if int(r["season"])==season]
   if len(tr)<20 or not va: raise SDVNativeBakeoffError(f"CFB_SDV_OUTER_FOLD_EMPTY:{season}")
   alpha=_choose_alpha(data,family,grid,season,constants)
   model=fit_native_score_model(tr,family=family,ridge_alpha=alpha,constants=constants)
   pred=[model.predict_means(r,constants) for r in va]
   folds.append({"season":season,"rows":len(va),"alpha":alpha,"rmse":_rmse(pred,va),
                 "alpha_at_grid_boundary":alpha in (grid[0],grid[-1])})
   all_pred.extend(pred); all_rows.extend(va)
  observed[family]={"selection_metric":_rmse(all_pred,all_rows),"folds":folds}
 selected=min(FAMILIES,key=lambda family:(observed[family]["selection_metric"],FAMILIES.index(family)))
 return {"schema":"CFB_SPORTSDATAVERSE_NATIVE_BAKEOFF_RESULT_V1",
         "selection_metric":"JOINT_HOME_AWAY_SCORE_RMSE","outer_validation_seasons":outer,
         "selected_family":selected,"selection_tie_break":"LOWEST_RMSE_THEN_FROZEN_FAMILY_ORDER",
         "observed":observed,"authority":{"model_p_created":False,"promotion_authority":False,
         "staking_authority":False,"truth_gate_authority":False,"official_authority":False}}
