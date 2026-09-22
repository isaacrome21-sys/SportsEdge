from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.mlb_run_machine import (
    DEFAULT_QUOTE_TTL_SECONDS, MLBMachineReport, MLBRunMachineError,
    _machine_result, _prepare_hybrid_quotes, machine_report_to_dict,
)

NOW=datetime(2026,9,22,17,0,0,tzinfo=timezone.utc)
FRESH=(NOW-timedelta(seconds=20)).isoformat()

def _row(**extra):
    row={"game_id":"g","market":"MONEYLINE","entity_id":"CHC","line":None,"side":"YES",
         "american_odds":120,"opposite_odds":-140,"model_p":.55,"bet_status":"MODEL_CANDIDATE",
         "reason":"OK","retrieved_at":FRESH}
    row.update(extra)
    return row

def test_machine_result_exposes_scored_presentation():
    out=_machine_result(0,_row(),current=NOW)
    assert out.scored_status=="ACTIONABLE"
    assert 0 < out.confidence_score <= 100
    assert out.fair_odds is not None and out.scored_market_p is not None
    assert out.timestamp_source=="PROVIDED"

def test_one_sided_row_is_blocked_in_scored_layer():
    row=_row(); del row["opposite_odds"]
    out=_machine_result(0,row,current=NOW)
    assert out.scored_status=="BLOCKED" and out.confidence_score==0
    assert "OPPOSITE_QUOTE_UNAVAILABLE" in out.score_reason_codes

def test_first_home_run_row_is_blocked_in_scored_layer():
    out=_machine_result(0,_row(market="FIRST_HOME_RUN",entity_id="p",american_odds=700,opposite_odds=-1200,model_p=.15),current=NOW)
    assert out.scored_status=="BLOCKED" and "N_WAY_DEVIG_UNFROZEN" in out.score_reason_codes

def test_blocked_engine_row_stays_blocked_in_scored_layer():
    out=_machine_result(0,_row(market="NRFI",entity_id="g",american_odds=-110,opposite_odds=-110,model_p=.60,
                               bet_status="BLOCKED",reason="LINEUP_MISSING"),current=NOW)
    assert out.scored_status=="BLOCKED" and out.confidence_score==0

def test_report_serializes_score_and_timestamp_fields():
    result=_machine_result(0,_row(market="HITS",entity_id="p",line=1.5,side="OVER",american_odds=105,
                                  opposite_odds=-125,model_p=.58),current=NOW)
    report=MLBMachineReport("HYBRID","2026-09-22",NOW.isoformat(),"PASS",(result,),(),{})
    payload=machine_report_to_dict(report)
    assert payload["results"][0]["confidence_score"]==result.confidence_score
    assert payload["results"][0]["scored_status"]=="ACTIONABLE"
    assert payload["results"][0]["timestamp_source"]=="PROVIDED"

def test_default_ttl_is_180_seconds():
    assert DEFAULT_QUOTE_TTL_SECONDS==180
    ok=_machine_result(0,_row(retrieved_at=(NOW-timedelta(seconds=180)).isoformat()),current=NOW)
    stale=_machine_result(0,_row(retrieved_at=(NOW-timedelta(seconds=181)).isoformat()),current=NOW)
    assert ok.scored_status=="ACTIONABLE"
    assert stale.scored_status=="BLOCKED" and "STALE_QUOTE" in stale.score_reason_codes

def test_missing_timestamp_is_stale_not_fresh():
    row=_row(); del row["retrieved_at"]
    out=_machine_result(0,row,current=NOW)
    assert out.scored_status=="BLOCKED" and out.confidence_score==0
    assert "QUOTE_TIMESTAMP_MISSING" in out.score_reason_codes
    assert out.timestamp_source=="MISSING"

def test_naive_or_invalid_timestamp_is_stale_and_labeled():
    naive=_machine_result(0,_row(retrieved_at="2026-09-22T16:59:50"),current=NOW)
    assert naive.scored_status=="BLOCKED" and "RETRIEVED_AT_TIMEZONE_REQUIRED" in naive.score_reason_codes
    assert naive.timestamp_source=="INVALID"
    bad=_machine_result(0,_row(retrieved_at="not-a-time"),current=NOW)
    assert bad.scored_status=="BLOCKED" and "RETRIEVED_AT_INVALID" in bad.score_reason_codes

def test_hybrid_intake_stamps_missing_timestamp_and_labels_it():
    out=_prepare_hybrid_quotes([{"market":"moneyline","american_odds":120}],current=NOW)
    assert out[0]["retrieved_at"]==NOW.isoformat()
    assert out[0]["timestamp_source"]=="INTAKE_STAMPED"
    assert out[0]["ttl_seconds"]==180

def test_hybrid_intake_preserves_provided_timestamp_and_labels_it():
    provided="2026-09-22T11:59:45-05:00"
    out=_prepare_hybrid_quotes([{"market":"moneyline","american_odds":120,"retrieved_at":provided}],current=NOW)
    assert out[0]["retrieved_at"]==provided
    assert out[0]["timestamp_source"]=="PROVIDED"

def test_hybrid_intake_refuses_naive_or_invalid_provided_timestamp():
    with pytest.raises(MLBRunMachineError,match="RETRIEVED_AT_TIMEZONE_REQUIRED"):
        _prepare_hybrid_quotes([{"market":"moneyline","retrieved_at":"2026-09-22T11:59:45"}],current=NOW)
    with pytest.raises(MLBRunMachineError,match="RETRIEVED_AT_INVALID"):
        _prepare_hybrid_quotes([{"market":"moneyline","retrieved_at":"yesterday"}],current=NOW)

def test_intake_stamped_result_is_labeled_not_book_observed():
    stamped=_prepare_hybrid_quotes([{"market":"moneyline"}],current=NOW)[0]["retrieved_at"]
    out=_machine_result(0,_row(retrieved_at=stamped),current=NOW,intake_stamp=NOW)
    assert out.timestamp_source=="INTAKE_STAMPED"
    provided=_machine_result(0,_row(),current=NOW,intake_stamp=NOW)
    assert provided.timestamp_source=="PROVIDED"
