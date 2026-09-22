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


def test_one_sided_machine_row_is_blocked_not_scored():
    row={
        "game_id":"g1","market":"MONEYLINE","selection":"HOME","line":None,
        "price_american":120,"estimate_p":0.60,
        "status":"ACTIONABLE","reason_codes":[],
    }
    result=_machine_result(row)
    assert result["scored_status"]=="BLOCKED"
    assert result["sportsedge_score"]==0
    assert result["market_probability"] is None
    assert "OPPOSITE_QUOTE_UNAVAILABLE" in result["score_reason_codes"]

def test_first_home_run_machine_row_is_blocked_until_nway_devig_is_frozen():
    row={
        "game_id":"g1","market":"FIRST_HOME_RUN","selection":"BATTER_1","line":None,
        "price_american":400,"opposite_price_american":-500,"estimate_p":0.25,
        "status":"ACTIONABLE","reason_codes":[],
    }
    result=_machine_result(row)
    assert result["scored_status"]=="BLOCKED"
    assert result["sportsedge_score"]==0
    assert result["market_probability"] is None
    assert "N_WAY_DEVIG_UNFROZEN" in result["score_reason_codes"]
