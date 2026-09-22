from sportsedge.mlb_input_readiness import required_feature_families, scored_input_readiness

def test_nrfi_requires_first_inning_and_environment():
    req=required_feature_families("NRFI")
    assert "first_inning" in req and "environment" in req and "lineup_pa" in req

def test_explicit_missing_family_blocks_score():
    ok,missing=scored_input_readiness({"market":"NRFI","bet_status":"MODEL_CANDIDATE","feature_family_readiness":{"first_inning":True}})
    assert not ok and "environment" in missing

def test_legacy_row_defers_to_upstream_gate():
    assert scored_input_readiness({"market":"HITS","bet_status":"MODEL_CANDIDATE"})==(True,())
    assert scored_input_readiness({"market":"HITS","bet_status":"BLOCKED"})[0] is False
