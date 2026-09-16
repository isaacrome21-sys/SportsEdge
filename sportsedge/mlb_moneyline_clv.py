"""Paired closing-line evidence for MLB MONEYLINE; downstream of Model_P."""
from __future__ import annotations
from math import isfinite
from statistics import fmean
from typing import Any,Iterable,Mapping
CLV_VERSION="mlb_moneyline_clv_v1"
class MLBMoneylineCLVError(ValueError):pass
def _american_prob(odds:Any)->float:
    try:x=float(odds)
    except (TypeError,ValueError) as e:raise MLBMoneylineCLVError("american odds must be numeric") from e
    if not isfinite(x) or x==0:raise MLBMoneylineCLVError("invalid american odds")
    return 100/(x+100) if x>0 else (-x)/((-x)+100)
def paired_no_vig(home_odds:Any,away_odds:Any)->tuple[float,float]:
    h,a=_american_prob(home_odds),_american_prob(away_odds);t=h+a
    if t<=0:raise MLBMoneylineCLVError("invalid paired market")
    return h/t,a/t
def evaluate_paired_closes(rows:Iterable[Mapping[str,Any]],*,min_mean_clv:float=.005)->dict[str,Any]:
    values=[]
    for i,row in enumerate(rows):
        if row.get("game_pk") in (None,""):raise MLBMoneylineCLVError(f"row {i}: game_pk required")
        side=str(row.get("model_side") or "").upper()
        if side not in {"HOME","AWAY"}:raise MLBMoneylineCLVError(f"row {i}: model_side must be HOME or AWAY")
        try:p=float(row.get("model_p"))
        except (TypeError,ValueError) as e:raise MLBMoneylineCLVError(f"row {i}: model_p invalid") from e
        if not isfinite(p) or not 0<p<1:raise MLBMoneylineCLVError(f"row {i}: model_p invalid")
        h,a=paired_no_vig(row.get("close_home_odds"),row.get("close_away_odds"));values.append(p-(h if side=="HOME" else a))
    if not values:return {"clv_version":CLV_VERSION,"n":0,"status":"BLOCKED_NO_ADMISSIBLE_PAIRED_CLOSES","promotion_authority":False}
    mean=fmean(values)
    return {"clv_version":CLV_VERSION,"n":len(values),"mean_model_directed_probability_clv":mean,"threshold":min_mean_clv,"clv_gate_pass":mean>=min_mean_clv,"status":"CLV_PASS_OTHER_GATES_REQUIRED" if mean>=min_mean_clv else "BLOCKED_CLV","promotion_authority":False,"devig_method":"MULTIPLICATIVE_V1"}
