"""Forward-only settlement and fixed-checkpoint evaluation for NFL V2G research evidence."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

POLICY_SCHEMA="SPORTSEDGE_NFL_V2G_PROSPECTIVE_EVALUATION_POLICY_V1"
SETTLEMENT_SCHEMA="SPORTSEDGE_NFL_V2G_PROSPECTIVE_SETTLEMENT_V1"
CHECKPOINT_SCHEMA="SPORTSEDGE_NFL_V2G_PROSPECTIVE_CHECKPOINT_V1"


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


def _profit(price: Any) -> float:
    p=_num(price,"NFL_V2G_EVAL_PRICE_INVALID")
    if p==0: raise ValueError("NFL_V2G_EVAL_PRICE_INVALID")
    return p/100.0 if p>0 else 100.0/(-p)


def validate_policy(policy: Mapping[str,Any]) -> None:
    if policy.get("schema_version")!=POLICY_SCHEMA or policy.get("status")!="FROZEN_BEFORE_FIRST_WEEK2_OUTCOME":
        raise ValueError("NFL_V2G_EVAL_POLICY_INVALID")
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
    rows=(clv_bundle or {}).get("rows") or []
    matches=[r for r in rows if r.get("market")==market]
    if len(matches)>1: raise ValueError(f"NFL_V2G_EVAL_DUPLICATE_CLV_ROW:{market}")
    return matches[0] if matches else None


def build_settlement(decision_bundle: Mapping[str,Any], binding: Mapping[str,Any]|None, clv_bundle: Mapping[str,Any]|None,
                     outcome: Mapping[str,Any], *, outcome_snapshot_sha256: str, observed_at: datetime, policy: Mapping[str,Any]) -> dict[str,Any]:
    validate_policy(policy)
    game_id=str(decision_bundle.get("game_id") or "")
    if str(outcome.get("game_id") or "")!=game_id: raise ValueError("NFL_V2G_EVAL_OUTCOME_GAME_MISMATCH")
    away,home=_game_codes(game_id)
    if str(outcome.get("away_team") or "")!=away or str(outcome.get("home_team") or "")!=home:
        raise ValueError("NFL_V2G_EVAL_OUTCOME_TEAM_MISMATCH")
    rows=list(decision_bundle.get("rows") or [])
    if not rows: raise ValueError("NFL_V2G_EVAL_DECISION_ROWS_EMPTY")
    kickoff=_dt(rows[0].get("game_start_ts"))
    delay=timedelta(hours=float(policy["outcome_source"]["minimum_hours_after_kickoff"]))
    if observed_at.astimezone(timezone.utc)<kickoff+delay: raise ValueError("NFL_V2G_EVAL_OUTCOME_TOO_EARLY")
    home_score=_num(outcome.get("home_score"),"NFL_V2G_EVAL_HOME_SCORE_MISSING")
    away_score=_num(outcome.get("away_score"),"NFL_V2G_EVAL_AWAY_SCORE_MISSING")
    margin,total=home_score-away_score,home_score+away_score
    settled=[]
    min_edge=float(policy["eligible_bet"]["minimum_decision_edge"])
    for d in rows:
        market=str(d.get("market") or "")
        if market not in {"spread","total"}: continue
        line=_num(d.get("line_at_decision"),"NFL_V2G_EVAL_LINE_MISSING")
        side=str(d.get("side") or "")
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
        clv=_clv_row(clv_bundle,market)
        reasons=[]
        if d.get("gate_result")!="SHADOW_QUALIFIED": reasons.append("DECISION_NOT_SHADOW_QUALIFIED")
        if _num(d.get("edge"),"NFL_V2G_EVAL_EDGE_INVALID")<min_edge: reasons.append("EDGE_BELOW_FROZEN_FLOOR")
        if not _binding_ready(binding,market): reasons.append("PAIRED_MARKET_BINDING_NOT_READY")
        if not clv or clv.get("status")!="CLV_ELIGIBLE": reasons.append("CLV_NOT_ELIGIBLE")
        elif abs(_num(clv.get("probability_line"),"NFL_V2G_EVAL_CLV_LINE_INVALID")-line)>1e-9: reasons.append("CLV_THRESHOLD_MISMATCH")
        settled.append({
            "market":market,"side":side,"line_at_decision":line,"price_at_decision":d.get("price_at_decision"),
            "model_prob":d.get("model_prob"),"decision_edge":d.get("edge"),"decision_ev":d.get("ev"),"result":result,"profit_units":profit,
            "clv":clv.get("clv") if clv and clv.get("status")=="CLV_ELIGIBLE" else None,
            "eligible_for_checkpoint":not reasons,"ineligibility_reasons":reasons,
        })
    return {
        "schema_version":SETTLEMENT_SCHEMA,"game_id":game_id,"kickoff_utc":kickoff.isoformat(),"observed_at_utc":observed_at.astimezone(timezone.utc).isoformat(),
        "outcome_snapshot_sha256":outcome_snapshot_sha256,"home_score":home_score,"away_score":away_score,"rows":settled,
        "promotion_authority":False,"may_create_model_p":False,"truth_gate_pass_granted":False,"official_status_granted":False,
    }


def _ece(rows: list[tuple[float,int]], bins: int) -> tuple[float,float]:
    if not rows: raise ValueError("NFL_V2G_EVAL_CALIBRATION_EMPTY")
    ece=maxdev=0.0; n=len(rows)
    for idx in range(bins):
        lo,hi=idx/bins,(idx+1)/bins
        bucket=[(p,y) for p,y in rows if lo<=p<(hi if idx<bins-1 else hi+1e-12)]
        if not bucket: continue
        mp=sum(p for p,_ in bucket)/len(bucket); my=sum(y for _,y in bucket)/len(bucket); dev=abs(mp-my)
        ece += len(bucket)/n*dev; maxdev=max(maxdev,dev)
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
            z=max(-35.0,min(35.0,a+b*x)); mu=1/(1+math.exp(-z)); w=max(1e-9,mu*(1-mu)); r=y-mu
            g0+=r; g1+=r*x; i00+=w; i01+=w*x; i11+=w*x*x
        det=i00*i11-i01*i01
        if abs(det)<1e-12: raise ValueError("NFL_V2G_EVAL_CALIBRATION_SINGULAR")
        da=(g0*i11-g1*i01)/det; db=(g1*i00-g0*i01)/det
        a+=da; b+=db
        if max(abs(da),abs(db))<1e-10: break
    return a,b


def evaluate_checkpoint(settlements: Iterable[Mapping[str,Any]], *, count: int, policy: Mapping[str,Any]) -> dict[str,Any]:
    validate_policy(policy)
    eligible=[]
    for bundle in settlements:
        for row in bundle.get("rows") or []:
            if row.get("eligible_for_checkpoint"):
                eligible.append({**row,"game_id":bundle.get("game_id"),"kickoff_utc":bundle.get("kickoff_utc")})
    eligible.sort(key=lambda r:(str(r.get("kickoff_utc")),str(r.get("game_id")),str(r.get("market"))))
    if len(eligible)<count: raise ValueError(f"NFL_V2G_EVAL_CHECKPOINT_NOT_REACHED:{len(eligible)}:{count}")
    rows=eligible[:count]
    mean_clv=sum(_num(r.get("clv"),"NFL_V2G_EVAL_CLV_INVALID") for r in rows)/count
    roi=sum(_num(r.get("profit_units"),"NFL_V2G_EVAL_PROFIT_INVALID") for r in rows)/count
    calibration=[(_num(r.get("model_prob"),"NFL_V2G_EVAL_MODEL_PROB_INVALID"),1 if r.get("result")=="WIN" else 0) for r in rows if r.get("result")!="PUSH"]
    bins=int(policy["gates"]["calibration_bins"]); ece,maxdev=_ece(calibration,bins)
    try: intercept,slope=_calibration_fit(calibration); calibration_error=None
    except ValueError as exc: intercept=slope=None; calibration_error=str(exc)
    g=policy["gates"]
    gates={
        "mean_clv":mean_clv>=float(g["mean_clv_min"]),"after_vig_roi":roi>=float(g["after_vig_roi_min"]),
        "ece":ece<=float(g["ece_max"]),"max_bin_deviation":maxdev<=float(g["max_nonempty_bin_abs_deviation"]),
        "calibration_slope":slope is not None and float(g["calibration_slope_min"])<=slope<=float(g["calibration_slope_max"]),
        "calibration_intercept":intercept is not None and abs(intercept)<=float(g["calibration_intercept_abs_max"]),
    }
    promotion_quality=count>=int(policy["checkpoints"]["first_promotion_quality_checkpoint"])
    status="FORWARD_EVIDENCE_GATE_PASS" if promotion_quality and all(gates.values()) else "FORWARD_EVIDENCE_GATE_FAIL" if promotion_quality else "CHECKPOINT_DIAGNOSTIC_ONLY"
    return {
        "schema_version":CHECKPOINT_SCHEMA,"checkpoint_count":count,"eligible_available_at_evaluation":len(eligible),"status":status,
        "metrics":{"mean_clv":mean_clv,"after_vig_roi":roi,"calibration_n":len(calibration),"calibration_slope":slope,"calibration_intercept":intercept,"ece":ece,"max_nonempty_bin_abs_deviation":maxdev,"calibration_error":calibration_error},
        "gates":gates,"row_identity":[[r["game_id"],r["market"]] for r in rows],
        "promotion_authority":False,"may_create_model_p":False,"market_eligibility_changed":False,"truth_gate_pass_granted":False,"official_status_granted":False,
    }
