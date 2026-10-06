from sportsedge.mlb_context_artifact import build_candidate_artifact

def test_artifact_requires_validated_pit_price_blind_source():
    v={"status":"VALIDATED"}
    try: build_candidate_artifact({},v,source_manifest={"pit_strict":False,"contains_sportsbook_prices":False})
    except ValueError: pass
    else: raise AssertionError("expected PIT rejection")
    try: build_candidate_artifact({},v,source_manifest={"pit_strict":True,"contains_sportsbook_prices":True})
    except ValueError: pass
    else: raise AssertionError("expected sportsbook rejection")

def test_artifact_identity_is_deterministic():
    v={"status":"VALIDATED","holdout_games":200}
    m={"pit_strict":True,"contains_sportsbook_prices":False,"source":"fixture"}
    a=build_candidate_artifact({"wind_mph":0.01},v,source_manifest=m)
    b=build_candidate_artifact({"wind_mph":0.01},v,source_manifest=m)
    assert a["artifact_id"]==b["artifact_id"]
    assert a["status"]=="VALIDATED"

