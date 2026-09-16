"""Assemble admissible forward MLB MONEYLINE evidence without granting authority."""
from __future__ import annotations
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Iterable, Mapping

DECISION_TARGET_MIN = 30.0
DECISION_EARLY_TOLERANCE_MIN = 6.0

class MLBMoneylineForwardLedgerError(ValueError):
    pass

def _ts(v: Any, name: str) -> datetime:
    try:
        d = datetime.fromisoformat(str(v or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise MLBMoneylineForwardLedgerError(f"{name}: invalid timestamp") from exc
    if d.tzinfo is None:
        raise MLBMoneylineForwardLedgerError(f"{name}: timezone required")
    return d.astimezone(timezone.utc)

def _prob(v: Any) -> float:
    try: p=float(v)
    except (TypeError, ValueError) as exc: raise MLBMoneylineForwardLedgerError("model_p invalid") from exc
    if not isfinite(p) or not 0<p<1: raise MLBMoneylineForwardLedgerError("model_p invalid")
    return p

def _quote(row: Mapping[str,Any]) -> tuple[float,float]:
    ml=row.get("moneyline")
    if not isinstance(ml,Mapping) or ml.get("status")!="OK": raise MLBMoneylineForwardLedgerError("paired moneyline required")
    try: h=float(ml["home_price_american"]); a=float(ml["away_price_american"])
    except (KeyError,TypeError,ValueError) as exc: raise MLBMoneylineForwardLedgerError("paired moneyline required") from exc
    if not isfinite(h) or not isfinite(a) or h==0 or a==0: raise MLBMoneylineForwardLedgerError("paired moneyline invalid")
    return h,a

def _minutes_before(row: Mapping[str,Any]) -> float:
    obs=_ts(row.get("observed_at_utc"),"observed_at_utc"); start=_ts(row.get("scheduled_start_utc"),"scheduled_start_utc")
    if not obs<start: raise MLBMoneylineForwardLedgerError("quote PIT violation")
    return (start-obs).total_seconds()/60.0

def assemble_forward_evidence(*, prediction: Mapping[str,Any], quotes: Iterable[Mapping[str,Any]], settlement: Mapping[str,Any]) -> dict[str,Any]:
    if prediction.get("market_blind") is not True: raise MLBMoneylineForwardLedgerError("prediction must be market_blind")
    game_pk=prediction.get("game_pk")
    if game_pk in (None,""): raise MLBMoneylineForwardLedgerError("prediction game_pk required")
    model_p=_prob(prediction.get("model_p")); side=str(prediction.get("model_side") or "").upper()
    if side not in {"HOME","AWAY"}: raise MLBMoneylineForwardLedgerError("model_side must be HOME or AWAY")
    feature_asof=_ts(prediction.get("feature_asof_ts"),"feature_asof_ts"); start=_ts(prediction.get("event_start_ts"),"event_start_ts"); generated=_ts(prediction.get("prediction_generated_at_utc"),"prediction_generated_at_utc")
    if not feature_asof<start or not generated<start: raise MLBMoneylineForwardLedgerError("prediction PIT violation")
    artifact=str(prediction.get("model_artifact_sha256") or "")
    if len(artifact)!=64: raise MLBMoneylineForwardLedgerError("model_artifact_sha256 required")
    candidates=[]
    for q in quotes:
        if str(q.get("sportsbook") or "").lower()!="draftkings": continue
        if str(q.get("model_artifact_sha256") or "")!=artifact: raise MLBMoneylineForwardLedgerError("model artifact mismatch")
        q_start=_ts(q.get("scheduled_start_utc"),"scheduled_start_utc")
        if abs((q_start-start).total_seconds())>1: raise MLBMoneylineForwardLedgerError("event start identity mismatch")
        _quote(q); mb=_minutes_before(q); obs=_ts(q.get("observed_at_utc"),"observed_at_utc")
        candidates.append((obs,mb,q))
    if not candidates: return {"status":"BLOCKED_NO_PAIRED_QUOTES","promotion_authority":False}
    decision=[x for x in candidates if DECISION_TARGET_MIN <= x[1] <= DECISION_TARGET_MIN+DECISION_EARLY_TOLERANCE_MIN and generated<=x[0]]
    if not decision: return {"status":"BLOCKED_NO_ADMISSIBLE_DECISION_QUOTE","promotion_authority":False}
    decision.sort(key=lambda x:(x[1],x[0]))
    d_obs,d_mb,dq=decision[0]
    close=[x for x in candidates if x[0]>=d_obs and x[0]<start]
    if not close: return {"status":"BLOCKED_NO_ADMISSIBLE_CLOSE","promotion_authority":False}
    close.sort(key=lambda x:x[0]); c_obs,c_mb,cq=close[-1]
    if settlement.get("game_pk")!=game_pk: raise MLBMoneylineForwardLedgerError("settlement identity mismatch")
    if str(settlement.get("status") or "").upper()!="FINAL": return {"status":"BLOCKED_NOT_FINAL","promotion_authority":False}
    try: home=int(settlement.get("home_score")); away=int(settlement.get("away_score"))
    except (TypeError,ValueError) as exc: raise MLBMoneylineForwardLedgerError("settlement scores invalid") from exc
    if home==away: raise MLBMoneylineForwardLedgerError("MLB final cannot be tied")
    outcome=1 if (home>away if side=="HOME" else away>home) else 0
    ch,ca=_quote(cq)
    return {
        "status":"FORWARD_EVIDENCE_COMPLETE",
        "promotion_authority":False,
        "game_pk":game_pk,
        "model_side":side,
        "model_p":model_p,
        "market_blind":True,
        "feature_asof_ts":feature_asof.isoformat(),
        "event_start_ts":start.isoformat(),
        "prediction_generated_at_utc":generated.isoformat(),
        "model_artifact_sha256":artifact,
        "decision_quote_observed_at_utc":d_obs.isoformat(),
        "decision_minutes_before_start":round(d_mb,4),
        "decision_provider_event_id":dq.get("provider_event_id"),
        "decision_raw_sha256":dq.get("raw_sha256"),
        "close_quote_observed_at_utc":c_obs.isoformat(),
        "close_minutes_before_start":round(c_mb,4),
        "close_provider_event_id":cq.get("provider_event_id"),
        "close_raw_sha256":cq.get("raw_sha256"),
        "close_home_odds":ch,
        "close_away_odds":ca,
        "outcome":outcome,
        "settlement_status":"FINAL",
        "settlement_home_score":home,
        "settlement_away_score":away,
        "decision_policy":"30m target; tolerance +6m EARLY_ONLY_AT_OR_BEFORE_TARGET",
        "close_policy":"last verifiable pre-first-pitch DraftKings paired quote",
    }
