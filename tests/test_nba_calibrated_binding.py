from datetime import datetime, timezone
import math
import pytest

from sportsedge.sports.nba.binding import NBAQuote
from sportsedge.sports.nba.calibration import NBACalibrator
from sportsedge.sports.nba.calibrated_binding import calibrated_fair_price, bind_calibrated_quote
from sportsedge.sports.nba.pricing import NBAFairPrice

NOW=datetime(2026,9,23,15,0,tzinfo=timezone.utc)


def test_calibration_preserves_push_mass_and_records_provenance():
    fair=NBAFairPrice(.50,.10,.40,1.8)
    cal=NBACalibrator(((0.5,0.6,.60,25),),"history-sha")
    out,prov=calibrated_fair_price(fair,model_version="m1",simulation_sha256="sim-sha",calibrator=cal)
    assert out.push_probability == .10
    assert math.isclose(out.win_probability+out.push_probability+out.lose_probability,1.0)
    assert out.win_probability != fair.win_probability
    assert prov.raw_probability == .50
    assert prov.calibration_sha256 == "history-sha"
    assert prov.simulation_sha256 == "sim-sha"


def test_no_calibrator_is_identity_not_manufactured_confidence():
    fair=NBAFairPrice(.56,0,.44,1/.56)
    out,prov=calibrated_fair_price(fair,model_version="m1",simulation_sha256="sim")
    assert out == fair
    assert prov.calibration_version is None
    assert prov.calibration_sha256 is None


def test_binding_uses_calibrated_probability_but_score_remains_quality_only():
    fair=NBAFairPrice(.55,0,.45,1/.55)
    cal=NBACalibrator(((0.5,0.6,.65,25),),"hist")
    q=NBAQuote("g1","TOTAL","OVER",225.5,2.0,"BOOK",NOW)
    edge,prov=bind_calibrated_quote(q,fair,as_of=NOW,model_version="m1",simulation_sha256="sim",model_quality=.81,context_quality=1.0,calibrator=cal)
    assert edge.fair.win_probability == prov.calibrated_probability
    assert edge.score == 90
    assert edge.score_version == "NBA_RUN_IT_SCORE_RULE_B_V2"


def test_invalid_probability_mass_or_missing_provenance_fails_closed():
    with pytest.raises(ValueError):
        calibrated_fair_price(NBAFairPrice(.7,0,.4,1.0),model_version="m",simulation_sha256="s")
    with pytest.raises(ValueError):
        calibrated_fair_price(NBAFairPrice(.5,0,.5,2.0),model_version="",simulation_sha256="s")
