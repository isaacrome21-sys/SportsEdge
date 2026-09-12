"""Forward-only fixed-checkpoint evaluation for NFL V2G research evidence.

Canonical postgame outcomes are written by the separate prospective outcome
capture lane. This module is read-only with respect to game results: it validates
those immutable outcome records, binds them to frozen decisions/market/CLV
evidence, and creates research-only settlement/checkpoint reports.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Iterable, Mapping

from .m2_v2g_forward import canonical_bytes

POLICY_SCHEMA="SPORTSEDGE_NFL_V2G_PROSPECTIVE_EVALUATION_POLICY_V1"
SETTLEMENT_SCHEMA="SPORTSEDGE_NFL_V2G_PROSPECTIVE_SETTLEMENT_V1"
CHECKPOINT_SCHEMA="SPORTSEDGE_NFL_V2G_PROSPECTIVE_CHECKPOINT_V1"
OUTCOME_SCHEMA="NFL_M2_V2G_PROSPECTIVE_OUTCOME_V1"
CLV_BUNDLE_SCHEMA="SPORTSEDGE_NFL_V2G_FORWARD_CLV_BUNDLE_V1"
CLV_ROW_SCHEMA="SPORTSEDGE_NFL_V2G_FORWARD_CLV_V1"
CLV_METRIC="CLOSING_NOVIG_MINUS_DECISION_NOVIG"


def _dt(value: Any) -> datetime:
    raw=str(value or "").strip()
    out=datetime.fromisoformat(raw[:-1]+"+00:00" if raw.endswith("Z") else raw)
    if out.tzinfo is None or out.utcoffset() is None: raise ValueError("NFL_V2G_EVAL_TIMESTAMP_NAIVE")
    return out.astimezone(timezone.utc)


def _num(value: Any, code: str) -> float:
    try: out=float(value)
    except (TypeError,ValueError) as exc: raise ValueError(code) from exc
    if not math.isfinite(out): raise ValueError(code)
    return out


def _prob(value: Any, code: str) -> float:
    out=_num(value,code)
    if out<0.0 or out>1.0: raise ValueError(code)
    return out


def _hex(value: Any, length: int, code: str) -> str:
    text=str(value or "").strip().lower()
    if len(text)!=length or any(ch not in "0123456789abcdef" for ch in text): raise ValueError(code)
    return text


def _profit(price: Any) -> float:
    p=_num(price,"NFL_V2G_EVAL_PRICE_INVALID")
    if p==0: raise ValueError("NFL_V2G_EVAL_PRICE_INVALID")
    return p/100.0 if p>0 else 100.0/(-p)


def validate_policy(policy: Mapping[str,Any]) -> None:
    if policy.get("schema_version")!=POLICY_SCHEMA or policy.get("status")!="FROZEN_BEFORE_FIRST_WEEK2_OUTCOME":
        raise ValueError("NFL_V2G_EVAL_POLICY_INVALID")
    source=policy.get("outcome_source") or {}
    if source.get("contract")!=OUTCOME_SCHEMA or source.get("direct_schedule_refetch_for_evaluation") is not False:
        raise ValueError("NFL_V2G_EVAL_OUTCOME_SOURCE_POLICY_INVALID")
    if float(source.get("minimum_hours_after_kickoff",0.0))<8.0:
        raise ValueError("NFL_V2G_EVAL_OUTCOME_DELAY_POLICY_INVALID")
    for key in ("promotion_authority","may_create_model_p","market_eligibility_changed","truth_gate_pass_granted","official_status_granted"):
        if policy.get(key) is not False: raise ValueError(f"NFL_V2G_EVAL_AUTHORITY_INVALID:{key}")
    checkpoints=list((policy.get("checkpoints") or {}).get("fixed_eligible_bet_counts") or [])
    if checkpoints!=sorted(set(checkpoints)) or not checkpoints: raise ValueError("NFL_V2G_EVAL_CHECKPOINTS_INVALID")


def _game_codes(game_id: str) -> tuple[str,str]:
    parts=str(game_id).split("_")
    if len(parts)!=4 or parts[0]!="2026": raise ValueError("NFL_V2G_EVAL_GAME_ID_INVALID")
    return parts[2],parts[3]


def _binding_ready(binding: Mapping[str,Any]|None, market: str) -> bool:
    if not binding: return False
    return (((binding.get("market_status") or {}).get(market) or {}).get("status")=="READY_FOR_PROSPECTIVE_EVALUATION")


def _clv_row(clv_bundle: Mapping[str,Any]|None, market: str) -> Mapping[str,Any]|None:
    if not clv_bundle: return None
    if clv_bundle.get("schema_version")!=CLV_BUNDLE_SCHEMA: raise ValueError("NFL_V2G_EVAL_CLV_BUNDLE_SCHEMA_INVALID")
    rows=clv_bundle.get("rows") or []
    matches=[r for r in rows if r.get("market")==market]
    if len(matches)>1: raise ValueError(f"NFL_V2G_EVAL_DUPLICATE_CLV_ROW:{market}")
    row=matches[0] if matches else None
    if row is not None and row.get("schema_version")!=CLV_ROW_SCHEMA: raise ValueError("NFL_V2G_EVAL_CLV_ROW_SCHEMA_INVALID")
    return row


def _validate_eligible_clv_row(clv: Mapping[str,Any], decision: Mapping[str,Any]) -> float:
    if clv.get("status")!="CLV_ELIGIBLE": raise ValueError("NFL_V2G_EVAL_CLV_STATUS_INVALID")
    if str(clv.get("game_id") or "")!=str(decision.get("game_id") or ""): raise ValueError("NFL_V2G_EVAL_CLV_GAME_MISMATCH")
    if str(clv.get("market") or "")!=str(decision.get("market") or ""): raise ValueError("NFL_V2G_EVAL_CLV_MARKET_MISMATCH")
    if str(clv.get("side") or "")!=str(decision.get("side") or ""): raise ValueError("NFL_V2G_EVAL_CLV_SIDE_MISMATCH")
    if abs(_prob(clv.get("decision_model_prob"),"NFL_V2G_EVAL_CLV_MODEL_PROB_INVALID")-_prob(decision.get("model_prob"),"NFL_V2G_EVAL_MODEL_PROB_INVALID"))>1e-12:
        raise ValueError("NFL_V2G_EVAL_CLV_MODEL_PROB_MISMATCH")
    decision_novig=_prob(decision.get("novig_prob"),"NFL_V2G_EVAL_DECISION_NOVIG_INVALID")
    clv_decision_novig=_prob(clv.get("decision_novig_prob"),"NFL_V2G_EVAL_CLV_DECISION_NOVIG_INVALID")
    closing_novig=_prob(clv.get("closing_novig_prob"),"NFL_V2G_EVAL_CLV_CLOSING_NOVIG_INVALID")
    if abs(clv_decision_novig-decision_novig)>1e-12: raise ValueError("NFL_V2G_EVAL_CLV_DECISION_NOVIG_MISMATCH")
    observed=_num(clv.get("clv"),"NFL_V2G_EVAL_CLV_INVALID")
    expected=closing_novig-decision_novig
    if abs(observed-expected)>1e-12: raise ValueError("NFL_V2G_EVAL_CLV_METRIC_MISMATCH")
    return observed


def _outcome_sha256(outcome: Mapping[str,Any]) -> str:
    payload=dict(outcome); payload.pop("outcome_sha256",None)
    return sha256(canonical_bytes(payload)).hexdigest()


def validate_canonical_outcome(outcome: Mapping[str,Any], decision_bundle: Mapping[str,Any], policy: Mapping[str,Any]) -> None:
    validate_policy(policy)
    if outcome.get("schema_version")!=OUTCOME_SCHEMA or outcome.get("status")!="PROSPECTIVE_RESEARCH_OUTCOME_CAPTURED":
        raise ValueError("NFL_V2G_EVAL_OUTCOME_SCHEMA_INVALID")
    if outcome.get("outcome_source")!="NFLVERSE_GAMES_CSV_POSTGAME_SCORE": raise ValueError("NFL_V2G_EVAL_OUTCOME_SOURCE_INVALID")
    for key in ("market_prices_consumed","promotion_authority","may_create_model_p","market_eligibility_changed","truth_gate_pass_granted","official_status_granted"):
        if outcome.get(key) is not False: raise ValueError(f"NFL_V2G_EVAL_OUTCOME_AUTHORITY_INVALID:{key}")
    game_id=str(decision_bundle.get("game_id") or "")
    if str(outcome.get("game_id") or "")!=game_id: raise ValueError("NFL_V2G_EVAL_OUTCOME_GAME_MISMATCH")
    away,home=_game_codes(game_id)
    if str(outcome.get("away_team") or "")!=away or str(outcome.get("home_team") or "")!=home: raise ValueError("NFL_V2G_EVAL_OUTCOME_TEAM_MISMATCH")
    rows=list(decision_bundle.get("rows") or [])
    if not rows: raise ValueError("NFL_V2G_EVAL_DECISION_ROWS_EMPTY")
    prediction_shas={str(r.get("prediction_sha256") or "").lower() for r in rows}
    artifact_shas={str(r.get("artifact_sha256") or "").lower() for r in rows}
    if len(prediction_shas)!=1 or _hex(outcome.get("prediction_sha256"),64,"NFL_V2G_EVAL_OUTCOME_PREDICTION_SHA_INVALID") not in prediction_shas:
        raise ValueError("NFL_V2G_EVAL_OUTCOME_PREDICTION_MISMATCH")
    if len(artifact_shas)!=1 or _hex(outcome.get("artifact_sha256"),64,"NFL_V2G_EVAL_OUTCOME_ARTIFACT_SHA_INVALID") not in artifact_shas:
        raise ValueError("NFL_V2G_EVAL_OUTCOME_ARTIFACT_MISMATCH")
    _hex(outcome.get("result_schedule_snapshot_sha256"),64,"NFL_V2G_EVAL_OUTCOME_SNAPSHOT_SHA_INVALID")
    _hex(outcome.get("prediction_capture_code_git_sha"),40,"NFL_V2G_EVAL_OUTCOME_CAPTURE_CODE_SHA_INVALID")
    _hex(outcome.get("settlement_code_git_sha"),40,"NFL_V2G_EVAL_OUTCOME_SETTLEMENT_CODE_SHA_INVALID")
    if str(outcome.get("outcome_sha256") or "").lower()!=_outcome_sha256(outcome): raise ValueError("NFL_V2G_EVAL_OUTCOME_SHA_MISMATCH")
    kickoff=_dt(outcome.get("kickoff_utc")); observed=_dt(outcome.get("observed_at_utc"))
    if kickoff!=_dt(rows[0].get("game_start_ts")): raise ValueError("NFL_V2G_EVAL_OUTCOME_KICKOFF_MISMATCH")
    recorded_delay=_num(outcome.get("minimum_hours_after_kickoff"),"NFL_V2G_EVAL_OUTCOME_DELAY_INVALID")
    required_delay=float(policy["outcome_source"]["minimum_hours_after_kickoff"])
    if recorded_delay<required_delay or observed<kickoff+timedelta(hours=recorded_delay): raise ValueError("NFL_V2G_EVAL_OUTCOME_TOO_EARLY")
    home_score=_num(outcome.get("home_score"),"NFL_V2G_EVAL_HOME_SCORE_MISSING")
    away_score=_num(outcome.get("away_score"),"NFL_V2G_EVAL_AWAY_SCORE_MISSING")
    if home_score<0 or away_score<0 or int(home_score)!=home_score or int(away_score)!=away_score: raise ValueError("NFL_V2G_EVAL_OUTCOME_SCORE_INVALID")
    if _num(outcome.get("final_margin_home_minus_away"),"NFL_V2G_EVAL_OUTCOME_MARGIN_INVALID")!=home_score-away_score: raise ValueError("NFL_V2G_EVAL_OUTCOME_MARGIN_INCONSISTENT")
    if _num(outcome.get("final_total"),"NFL_V2G_EVAL_OUTCOME_TOTAL_INVALID")!=home_score+away_score: raise ValueError("NFL_V2G_EVAL_OUTCOME_TOTAL_INCONSISTENT")


def build_settlement(decision_bundle: Mapping[str,Any], binding: Mapping[str,Any]|None, clv_bundle: Mapping[str,Any]|None,
                     outcome: Mapping[str,Any], *, policy: Mapping[str,Any]) -> dict[str,Any]:
    validate_canonical_outcome(outcome,decision_bundle,policy)
    game_id=str(decision_bundle.get("game_id") or "")
    if clv_bundle and str(clv_bundle.get("game_id") or "")!=game_id: raise ValueError("NFL_V2G_EVAL_CLV_BUNDLE_GAME_MISMATCH")
    away,home=_game_codes(game_id)
    rows=list(decision_bundle.get("rows") or [])
    kickoff=_dt(rows[0].get("game_start_ts"))
    home_score=_num(outcome.get("home_score"),"NFL_V2G_EVAL_HOME_SCORE_MISSING")
    away_score=_num(outcome.get("away_score"),"NFL_V2G_EVAL_AWAY_SCORE_MISSING")
    margin,total=home_score-away_score,home_score+away_score
    settled=[]; min_edge=float(policy["eligible_bet"]["minimum_decision_edge"])
    for d in rows:
        market=str(d.get("market") or "")
        if market not in {"spread","total"}: continue
        decision={**d,"game_id":game_id}; line=_num(d.get("line_at_decision"),"NFL_V2G_EVAL_LINE_MISSING"); side=str(d.get("side") or "")
        if market=="spread":
            if side==home: value=margin+line
            elif side==away: value=-margin+line
            else: raise ValueError("NFL_V2G_EVAL_SPREAD_SIDE_INVALID")
        else:
            if side=="over": value=total-line
            elif side=="under": value=line-total
            else: raise ValueError("NFL_V2G_EVAL_TOTAL_SIDE_INVALID")
        result="WIN" if value>0 else "LOSS" if value<0 else "PUSH"
        profit=_profit(d.get("price_at_decision")) if result=="WIN" else -1.0 if result=="LOSS" else 0.0
        clv=_clv_row(clv_bundle,market); reasons=[]; clv_value=None
        if d.get("gate_result")!="SHADOW_QUALIFIED": reasons.append("DECISION_NOT_SHADOW_QUALIFIED")
        if _num(d.get("edge"),"NFL_V2G_EVAL_EDGE_INVALID")<min_edge: reasons.append("EDGE_BELOW_FROZEN_FLOOR")
        if not _binding_ready(binding,market): reasons.append("PAIRED_MARKET_BINDING_NOT_READY")
        if not clv or clv.get("status")!="CLV_ELIGIBLE": reasons.append("CLV_NOT_ELIGIBLE")
        else:
            if abs(_num(clv.get("probability_line"),"NFL_V2G_EVAL_CLV_LINE_INVALID")-line)>1e-9: reasons.append("CLV_THRESHOLD_MISMATCH")
            clv_value=_validate_eligible_clv_row(clv,decision)
        settled.append({"market":market,"side":side,"line_at_decision":line,"price_at_decision":d.get("price_at_decision"),"model_prob":d.get("model_prob"),"decision_edge":d.get("edge"),"decision_ev":d.get("ev"),"result":result,"profit_units":profit,"clv":clv_value,"clv_metric":CLV_METRIC if clv_value is not None else None,"eligible_for_checkpoint":not reasons,"ineligibility_reasons":reasons})
    return {"schema_version":SETTLEMENT_SCHEMA,"game_id":game_id,"kickoff_utc":kickoff.isoformat(),"outcome_sha256":outcome["outcome_sha256"],"outcome_prediction_sha256":outcome["prediction_sha256"],"outcome_artifact_sha256":outcome["artifact_sha256"],"outcome_snapshot_sha256":outcome["result_schedule_snapshot_sha256"],"outcome_observed_at_utc":outcome["observed_at_utc"],"home_score":home_score,"away_score":away_score,"rows":settled,"promotion_authority":False,"may_create_model_p":False,"market_eligibility_changed":False,"truth_gate_pass_granted":False,"official_status_granted":False}


def _ece(rows: list[tuple[float,int]], bins: int) -> tuple[float,float]:
    if not rows: raise ValueError("NFL_V2G_EVAL_CALIBRATION_EMPTY")
    ece=maxdev=0.0; n=len(rows)
    for idx in range(bins):
        lo,hi=idx/bins,(idx+1)/bins; bucket=[(p,y) for p,y in rows if lo<=p<(hi if idx<bins-1 else hi+1e-12)]
        if not bucket: continue
        mp=sum(p for p,_ in bucket)/len(bucket); my=sum(y for _,y in bucket)/len(bucket); dev=abs(mp-my); ece += len(bucket)/n*dev; maxdev=max(maxdev,dev)
    return ece,maxdev


def _calibration_fit(rows: list[tuple[float,int]]) -> tuple[float,float]:
    if len(rows)<2 or len({y for _,y in rows})<2: raise ValueError("NFL_V2G_EVAL_CALIBRATION_VARIATION_INSUFFICIENT")
    xs=[]
    for p,y in rows:
        q=min(1-1e-6,max(1e-6,p)); xs.append((math.log(q/(1-q)),y))
    a,b=0.0,1.0
    for _ in range(50):
        g0=g1=i00=i01=i11=0.0
        for x,y in xs:
            z=max(-35.0,min(35.0,a+b*x)); mu=1/(1+math.exp(-z)); w=max(1e-9,mu*(1-mu)); r=y-mu; g0+=r; g1+=r*x; i00+=w; i01+=w*x; i11+=w*x*x
        det=i00*i11-i01*i01
        if abs(det)<1e-12: raise ValueError("NFL_V2G_EVAL_CALIBRATION_SINGULAR")
        da=(g0*i11-g1*i01)/det; db=(g1*i00-g0*i01)/det; a+=da; b+=db
        if max(abs(da),abs(db))<1e-10: break
    return a,b


def evaluate_checkpoint(settlements: Iterable[Mapping[str,Any]], *, count: int, policy: Mapping[str,Any]) -> dict[str,Any]:
    validate_policy(policy); eligible=[]
    for bundle in settlements:
        for row in bundle.get("rows") or []:
            if row.get("eligible_for_checkpoint"):
                if row.get("clv_metric")!=CLV_METRIC: raise ValueError("NFL_V2G_EVAL_CHECKPOINT_CLV_METRIC_INVALID")
                eligible.append({**row,"game_id":bundle.get("game_id"),"kickoff_utc":bundle.get("kickoff_utc")})
    eligible.sort(key=lambda r:(str(r.get("kickoff_utc")),str(r.get("game_id")),str(r.get("market"))))
    if len(eligible)<count: raise ValueError(f"NFL_V2G_EVAL_CHECKPOINT_NOT_REACHED:{len(eligible)}:{count}")
    rows=eligible[:count]; mean_clv=sum(_num(r.get("clv"),"NFL_V2G_EVAL_CLV_INVALID") for r in rows)/count; roi=sum(_num(r.get("profit_units"),"NFL_V2G_EVAL_PROFIT_INVALID") for r in rows)/count
    calibration=[(_num(r.get("model_prob"),"NFL_V2G_EVAL_MODEL_PROB_INVALID"),1 if r.get("result")=="WIN" else 0) for r in rows if r.get("result")!="PUSH"]
    bins=int(policy["gates"]["calibration_bins"]); ece,maxdev=_ece(calibration,bins)
    try: intercept,slope=_calibration_fit(calibration); calibration_error=None
    except ValueError as exc: intercept=slope=None; calibration_error=str(exc)
    g=policy["gates"]; gates={"mean_clv":mean_clv>=float(g["mean_clv_min"]),"after_vig_roi":roi>=float(g["after_vig_roi_min"]),"ece":ece<=float(g["ece_max"]),"max_bin_deviation":maxdev<=float(g["max_nonempty_bin_abs_deviation"]),"calibration_slope":slope is not None and float(g["calibration_slope_min"])<=slope<=float(g["calibration_slope_max"]),"calibration_intercept":intercept is not None and abs(intercept)<=float(g["calibration_intercept_abs_max"])}
    promotion_quality=count>=int(policy["checkpoints"]["first_promotion_quality_checkpoint"]); status="FORWARD_EVIDENCE_GATE_PASS" if promotion_quality and all(gates.values()) else "FORWARD_EVIDENCE_GATE_FAIL" if promotion_quality else "CHECKPOINT_DIAGNOSTIC_ONLY"
    return {"schema_version":CHECKPOINT_SCHEMA,"checkpoint_count":count,"eligible_available_at_evaluation":len(eligible),"status":status,"metrics":{"mean_clv":mean_clv,"after_vig_roi":roi,"calibration_n":len(calibration),"calibration_slope":slope,"calibration_intercept":intercept,"ece":ece,"max_nonempty_bin_abs_deviation":maxdev,"calibration_error":calibration_error,"clv_metric":CLV_METRIC},"gates":gates,"row_identity":[[r["game_id"],r["market"]] for r in rows],"promotion_authority":False,"may_create_model_p":False,"market_eligibility_changed":False,"truth_gate_pass_granted":False,"official_status_granted":False}
