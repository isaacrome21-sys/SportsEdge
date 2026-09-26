from datetime import datetime, timedelta, timezone

from sportsedge.sports.nba.training import NBATrainingRow
from sportsedge.sports.nba.possession_history import NBAPossessionObservation
from sportsedge.sports.nba.pace_fit import fit_pace_efficiency_with_possessions, pace_holdout_mae

UTC = timezone.utc


def pair(i, expected, actual):
    tip = datetime(2025, 1, i, 1, tzinfo=UTC)
    asof = tip - timedelta(hours=2)
    row = NBATrainingRow(str(i), tip, asof, "H", "A", expected, 115, 112, 113, 114, 110, 105, "f-v1")
    obs = NBAPossessionObservation(str(i), tip, asof, tip + timedelta(hours=3), actual, "provider", "box-v1")
    return row, obs


def test_real_targets_fit_pace_bias_and_bind_provenance():
    pairs = [pair(1, 99, 101), pair(2, 100, 104)]
    model = fit_pace_efficiency_with_possessions([x[0] for x in pairs], [x[1] for x in pairs])
    assert model.pace_bias == 3.0
    assert model.version.startswith("NBA_PACE_EFFICIENCY_OBS_V1:")


def test_holdout_mae_uses_observed_possessions():
    train = [pair(1, 99, 101), pair(2, 100, 104)]
    model = fit_pace_efficiency_with_possessions([x[0] for x in train], [x[1] for x in train])
    holdout = pair(3, 100, 102)
    assert pace_holdout_mae(model, [holdout[0]], [holdout[1]]) == 1.0
