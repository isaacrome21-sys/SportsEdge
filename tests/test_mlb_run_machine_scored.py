from sportsedge.mlb_run_machine import _machine_result, machine_report_to_dict, MLBMachineReport

def test_machine_result_exposes_scored_presentation():
    row={"game_id":"g","market":"MONEYLINE","entity_id":"CHC","line":None,"side":"YES",
         "american_odds":120,"model_p":.55,"bet_status":"MODEL_CANDIDATE","reason":"OK"}
    out=_machine_result(0,row)
    assert out.scored_status=="ACTIONABLE"
    assert 0 < out.confidence_score <= 100
    assert out.fair_odds is not None and out.scored_market_p is not None

def test_blocked_engine_row_stays_blocked_in_scored_layer():
    row={"game_id":"g","market":"NRFI","entity_id":"g","line":None,"side":"YES",
         "american_odds":-110,"model_p":.60,"bet_status":"BLOCKED","reason":"LINEUP_MISSING"}
    out=_machine_result(0,row)
    assert out.scored_status=="BLOCKED" and out.confidence_score==0

def test_report_serializes_score_fields():
    row={"game_id":"g","market":"HITS","entity_id":"p","line":1.5,"side":"OVER",
         "american_odds":105,"model_p":.58,"bet_status":"MODEL_CANDIDATE","reason":"OK"}
    result=_machine_result(0,row)
    report=MLBMachineReport("HYBRID","2026-09-21","2026-09-21T12:00:00+00:00","PASS",(result,),(),{})
    payload=machine_report_to_dict(report)
    assert payload["results"][0]["confidence_score"]==result.confidence_score
    assert payload["results"][0]["scored_status"]=="ACTIONABLE"
