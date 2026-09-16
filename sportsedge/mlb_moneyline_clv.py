"""Paired closing-line evidence for MLB MONEYLINE; downstream of Model_P.

Closing prices never enter Model_P. Fair closing probabilities are derived with
SportsEdge's frozen de-vig policy and fail closed on longshot sensitivity.
"""
from __future__ import annotations
from math import isfinite
from statistics import fmean
from typing import Any, Iterable, Mapping

from .devig import DevigError, devig_with_policy
from .edge_floors import EdgeFloorError, load_edge_floor_config, require_frozen_devig_policy
from .truth_gate import TruthGateError

CLV_VERSION = "mlb_moneyline_clv_v2_frozen_devig"

class MLBMoneylineCLVError(ValueError):
    pass

def _pair(game_pk: Any, home_odds: Any, away_odds: Any) -> tuple[dict[str,Any],dict[str,Any]]:
    base={"game_id":str(game_pk),"period":"FG","market":"MONEYLINE","entity_id":str(game_pk),"book_key":"draftkings","is_alternate":False,"line":0.0}
    home={**base,"side":"HOME_ML","american_odds":home_odds}
    away={**base,"side":"AWAY_ML","american_odds":away_odds}
    return home,away

def _policy(config: Mapping[str,Any] | None):
    try:
        cfg=config if config is not None else load_edge_floor_config()
        return require_frozen_devig_policy(config=cfg)
    except EdgeFloorError as exc:
        raise MLBMoneylineCLVError(f"frozen devig policy required: {exc}") from exc

def paired_no_vig(home_odds: Any, away_odds: Any, *, config: Mapping[str,Any] | None=None) -> tuple[float,float]:
    """Return the frozen estimator's two-sided fair probabilities."""
    policy=_policy(config); home,away=_pair("PAIR",home_odds,away_odds)
    try:
        result=devig_with_policy(home,away,policy=policy)
    except (DevigError, TruthGateError) as exc:
        raise MLBMoneylineCLVError(str(exc)) from exc
    return result.selected.candidate_fair_probability,result.selected.opposite_fair_probability

def evaluate_paired_closes(rows: Iterable[Mapping[str,Any]], *, min_mean_clv: float=.005, config: Mapping[str,Any] | None=None) -> dict[str,Any]:
    policy=_policy(config); values=[]; spreads=[]; longshots=0
    for i,row in enumerate(rows):
        game_pk=row.get("game_pk")
        if game_pk in (None,""): raise MLBMoneylineCLVError(f"row {i}: game_pk required")
        side=str(row.get("model_side") or "").upper()
        if side not in {"HOME","AWAY"}: raise MLBMoneylineCLVError(f"row {i}: model_side must be HOME or AWAY")
        try: p=float(row.get("model_p"))
        except (TypeError,ValueError) as exc: raise MLBMoneylineCLVError(f"row {i}: model_p invalid") from exc
        if not isfinite(p) or not 0<p<1: raise MLBMoneylineCLVError(f"row {i}: model_p invalid")
        home,away=_pair(game_pk,row.get("close_home_odds"),row.get("close_away_odds"))
        candidate,opposite=(home,away) if side=="HOME" else (away,home)
        try: result=devig_with_policy(candidate,opposite,policy=policy)
        except (DevigError, TruthGateError) as exc: raise MLBMoneylineCLVError(f"row {i}: {exc}") from exc
        values.append(p-result.selected.candidate_fair_probability)
        spreads.append(result.sensitivity_spread_probability_points)
        longshots+=int(result.longshot_triggered)
    if not values:
        return {"clv_version":CLV_VERSION,"n":0,"status":"BLOCKED_NO_ADMISSIBLE_PAIRED_CLOSES","promotion_authority":False}
    mean=fmean(values)
    return {
        "clv_version":CLV_VERSION,
        "n":len(values),
        "mean_model_directed_probability_clv":mean,
        "threshold":min_mean_clv,
        "clv_gate_pass":mean>=min_mean_clv,
        "status":"CLV_PASS_OTHER_GATES_REQUIRED" if mean>=min_mean_clv else "BLOCKED_CLV",
        "promotion_authority":False,
        "devig_policy_id":policy.policy_id,
        "devig_method":policy.stable_candidate_estimator,
        "longshot_candidate_estimator":policy.longshot_candidate_estimator,
        "longshot_rows":longshots,
        "max_sensitivity_spread_probability_points":max(spreads,default=0.0),
        "sensitivity_limit_absolute_probability_points":float(policy.sensitivity_limit_absolute_probability_points),
    }
