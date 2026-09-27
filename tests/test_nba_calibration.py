from datetime import datetime,timedelta,timezone
import pytest
from sportsedge.sports.nba.calibration import NBAProbabilityObservation,fit_temporal_calibrator,calibration_digest
UTC=timezone.utc

def obs(i,p,won,settle_days=0):
    tip=datetime(2025,1,i,1,tzinfo=UTC)
    return NBAProbabilityObservation(str(i),"ML_HOME",tip-timedelta(hours=2),tip,tip+timedelta(hours=3,days=settle_days),p,won,"m1")

def test_temporal_fit_excludes_unsettled_future_rows_and_is_deterministic():
    rows=[obs(1,.61,True),obs(2,.64,False),obs(3,.62,True,settle_days=10)]
    asof=datetime(2025,1,4,tzinfo=UTC)
    c=fit_temporal_calibrator(rows,as_of=asof)
    assert c.training_sha256==calibration_digest(rows[:2])
    assert c==fit_temporal_calibrator(reversed(rows),as_of=asof)

def test_sparse_calibration_shrinks_instead_of_claiming_certainty():
    c=fit_temporal_calibrator([obs(1,.61,True)],as_of=datetime(2025,1,2,tzinfo=UTC))
    q=c.calibrate(.61)
    assert .61 < q < 1.0

def test_rejects_post_tipoff_prediction():
    r=obs(1,.6,True)
    bad=NBAProbabilityObservation(r.game_id,r.market_key,r.tipoff,r.tipoff,r.settled_at,r.probability,r.won,r.model_version)
    with pytest.raises(ValueError,match="temporal order"):
        bad.validate()
