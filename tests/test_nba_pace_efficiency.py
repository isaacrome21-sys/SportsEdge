from datetime import datetime, timedelta, timezone
from sportsedge.sports.nba.training import NBATrainingRow
from sportsedge.sports.nba.pace_efficiency import fit_pace_efficiency, predict_state

UTC=timezone.utc

def row(i,hp,ap):
    tip=datetime(2025,1,i,1,tzinfo=UTC)
    return NBATrainingRow(str(i),tip,tip-timedelta(hours=2),"H","A",100,114,112,113,111,hp,ap,"v1")

def test_fit_is_deterministic_and_provenanced():
    data=[row(1,120,110),row(2,115,118),row(3,108,105)]
    a=fit_pace_efficiency(data); b=fit_pace_efficiency(reversed(data))
    assert a == b
    assert len(a.training_sha256)==64 and a.training_rows==3

def test_prediction_uses_fitted_bias_and_preserves_source_pace():
    data=[row(1,120,110),row(2,115,118)]
    model=fit_pace_efficiency(data)
    p=predict_state(model,row(3,108,105))
    assert p["expected_possessions"]==100
    assert p["model_version"]=="NBA_PACE_EFFICIENCY_BASELINE_V1"
    assert p["home_residual_sd"] >= 0

def test_fit_requires_real_training_rows():
    import pytest
    with pytest.raises(ValueError):
        fit_pace_efficiency([row(1,100,100)])
