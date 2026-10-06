from sportsedge.mlb_context_eligibility import context_eligibility

def test_closed_roof_disables_weather_and_f5_bullpen():
    b={"weather_roof":{"status":"AVAILABLE","roof_state":"closed"},"park_venue":{"status":"AVAILABLE"},
       "bullpen_workload":{"status":"AVAILABLE"}}
    e=context_eligibility(b)
    assert e["roof_closed"] is True
    assert e["lanes"]["weather"] is False
    assert e["lanes"]["bullpen_full_game"] is True
    assert e["lanes"]["bullpen_f5"] is False

def test_incomplete_lineup_is_neutral_not_eligible():
    b={"lineups":{"status":"AVAILABLE","complete_by_side":{"away":True,"home":False}}}
    assert context_eligibility(b)["lanes"]["lineups"] is False

def test_umpire_requires_sample_gate():
    b={"umpire":{"status":"AVAILABLE","home_plate_games":19}}
    assert context_eligibility(b)["lanes"]["umpire"] is False
    b["umpire"]["home_plate_games"]=20
    assert context_eligibility(b)["lanes"]["umpire"] is True

