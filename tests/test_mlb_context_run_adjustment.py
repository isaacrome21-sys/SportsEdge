from sportsedge.mlb_context_run_adjustment import apply_validated_run_adjustment, MLBContextArtifactError

def test_no_artifact_is_exact_baseline():
    a,h,m=apply_validated_run_adjustment(4.2,3.8,{"features":{"temperature_f":90}},None)
    assert (a,h)==(4.2,3.8)
    assert m["status"]=="BASELINE"

def test_validated_artifact_can_move_means_and_is_capped():
    art={"artifact_version":"mlb_context_run_adjustment_artifact_v1","status":"VALIDATED","feature_schema_version":"mlb_context_model_features_v1","artifact_id":"fixture","coefficients":{"temperature_f":1.0},"max_abs_log_multiplier":0.1}
    a,h,m=apply_validated_run_adjustment(4.0,4.0,{"features":{"temperature_f":100}},art)
    assert a>4.0 and h>4.0
    assert m["multiplier"] < 1.11

def test_unvalidated_artifact_fails_closed():
    art={"artifact_version":"mlb_context_run_adjustment_artifact_v1","status":"CANDIDATE","feature_schema_version":"mlb_context_model_features_v1","coefficients":{}}
    try: apply_validated_run_adjustment(4,4,{"features":{}},art)
    except MLBContextArtifactError: pass
    else: raise AssertionError("expected fail closed")

