from datetime import datetime, timedelta, timezone
import pytest
from sportsedge.sports.nba.training import NBATrainingRow
from sportsedge.sports.nba.possession_history import NBAPossessionObservation, bind_possession_targets, possession_digest

UTC=timezone.utc

def fixtures():
    tip=datetime(2025,1,2,1,tzinfo=UTC); asof=tip-timedelta(hours=2)
    train=NBATrainingRow("g1",tip,asof,"H","A",99.5,115,112,113,114,110,105,"features-v1")
    obs=NBAPossessionObservation("g1",tip,asof,tip+timedelta(hours=3),101.0,"provider","box-v1")
    return train,obs

def test_target_binds_only_on_game_tipoff_and_feature_timestamp():
    train,obs=fixtures()
    pairs=bind_possession_targets([train],[obs])
    assert pairs == ((train,101.0),)
    assert len(possession_digest([obs])) == 64

def test_pregame_or_at_tipoff_target_fails_closed():
    train,obs=fixtures()
    bad=NBAPossessionObservation(obs.game_id,obs.tipoff,obs.feature_as_of,obs.tipoff,101,"provider","v1")
    with pytest.raises(ValueError,match="observed after tipoff"):
        bad.validate()

def test_timestamp_mismatch_rejected_instead_of_backfilled():
    train,obs=fixtures()
    bad=NBAPossessionObservation(obs.game_id,obs.tipoff,obs.feature_as_of-timedelta(minutes=1),obs.observed_at,101,"provider","v1")
    with pytest.raises(ValueError,match="feature timestamp mismatch"):
        bind_possession_targets([train],[bad])

def test_duplicate_provider_targets_rejected():
    train,obs=fixtures()
    with pytest.raises(ValueError,match="duplicate"):
        bind_possession_targets([train],[obs,obs])
