from datetime import datetime,timedelta,timezone
import pytest
from sportsedge.mlb_moneyline_forward_ledger import MLBMoneylineForwardLedgerError,assemble_forward_evidence,evidence_rows_for_gates

def _base():
    start=datetime(2026,9,20,19,10,tzinfo=timezone.utc)
    art="a"*64
    pred={"game_pk":123,"model_side":"HOME","model_p":.58,"market_blind":True,"feature_asof_ts":(start-timedelta(hours=4)).isoformat(),"event_start_ts":start.isoformat(),"prediction_generated_at_utc":(start-timedelta(minutes=40)).isoformat(),"model_artifact_sha256":art}
    def q(m,home=-125,away=110):
        return {"sportsbook":"draftkings","model_artifact_sha256":art,"scheduled_start_utc":start.isoformat(),"observed_at_utc":(start-timedelta(minutes=m)).isoformat(),"provider_event_id":"dk-1","raw_sha256":str(int(m)).zfill(64),"moneyline":{"status":"OK","home_price_american":home,"away_price_american":away}}
    settlement={"game_pk":123,"status":"FINAL","home_score":5,"away_score":3}
    return pred,q,settlement

def _complete():
    pred,q,settlement=_base()
    return assemble_forward_evidence(prediction=pred,quotes=[q(35),q(30.5),q(9)],settlement=settlement)

def test_complete_uses_early_only_decision_and_latest_close():
    out=_complete()
    assert out["status"]=="FORWARD_EVIDENCE_COMPLETE"
    assert out["decision_minutes_before_start"]==pytest.approx(30.5)
    assert out["close_minutes_before_start"]==pytest.approx(9)
    assert out["outcome"]==1
    assert out["promotion_authority"] is False

def test_late_29_minute_quote_does_not_qualify_as_decision():
    pred,q,settlement=_base()
    out=assemble_forward_evidence(prediction=pred,quotes=[q(29),q(8)],settlement=settlement)
    assert out["status"]=="BLOCKED_NO_ADMISSIBLE_DECISION_QUOTE"

def test_prediction_must_precede_decision_quote():
    pred,q,settlement=_base(); start=datetime.fromisoformat(pred["event_start_ts"])
    pred["prediction_generated_at_utc"]=(start-timedelta(minutes=31)).isoformat()
    out=assemble_forward_evidence(prediction=pred,quotes=[q(35),q(8)],settlement=settlement)
    assert out["status"]=="BLOCKED_NO_ADMISSIBLE_DECISION_QUOTE"

def test_artifact_mismatch_fails_closed():
    pred,q,settlement=_base(); bad=q(31); bad["model_artifact_sha256"]="b"*64
    with pytest.raises(MLBMoneylineForwardLedgerError,match="artifact mismatch"):
        assemble_forward_evidence(prediction=pred,quotes=[bad],settlement=settlement)

def test_nonfinal_settlement_blocks():
    pred,q,settlement=_base(); settlement["status"]="LIVE"
    out=assemble_forward_evidence(prediction=pred,quotes=[q(31),q(5)],settlement=settlement)
    assert out["status"]=="BLOCKED_NOT_FINAL"

def test_market_blindness_required():
    pred,q,settlement=_base(); pred["market_blind"]=False
    with pytest.raises(MLBMoneylineForwardLedgerError,match="market_blind"):
        assemble_forward_evidence(prediction=pred,quotes=[q(31)],settlement=settlement)

def test_complete_record_projects_into_existing_gate_shapes():
    cal,clv=evidence_rows_for_gates([_complete()])
    assert cal==[{"model_p":.58,"outcome":1,"market_blind":True,"feature_asof_ts":cal[0]["feature_asof_ts"],"event_start_ts":cal[0]["event_start_ts"]}]
    assert clv[0]["game_pk"]==123 and clv[0]["model_side"]=="HOME" and clv[0]["close_home_odds"]==-125.0

def test_incomplete_record_cannot_reach_gate_projection():
    with pytest.raises(MLBMoneylineForwardLedgerError,match="incomplete"):
        evidence_rows_for_gates([{"status":"BLOCKED_NO_ADMISSIBLE_CLOSE","promotion_authority":False}])
