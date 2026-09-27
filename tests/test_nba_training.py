from datetime import datetime, timedelta, timezone
import pytest
from sportsedge.sports.nba.training import NBATrainingRow, chronological_split, training_digest

UTC=timezone.utc

def row(game, day, asof_hours=2):
    tip=datetime(2025,1,day,1,tzinfo=UTC)
    return NBATrainingRow(game,tip,tip-timedelta(hours=asof_hours),"H","A",99.5,115,112,113,114,110,105,"fixture-v1")

def test_chronological_split_is_temporal_and_deterministic():
    rows=[row("g2",2),row("g1",1),row("g3",3)]
    train,val=chronological_split(rows,validation_start=datetime(2025,1,3,tzinfo=UTC))
    assert [r.game_id for r in train] == ["g1","g2"]
    assert [r.game_id for r in val] == ["g3"]
    assert training_digest(rows) == training_digest(reversed(rows))

def test_future_or_at_tipoff_features_fail_closed():
    bad=row("g",1,0)
    with pytest.raises(ValueError,match="strictly before tipoff"):
        bad.validate()

def test_split_requires_both_sides():
    with pytest.raises(ValueError,match="non-empty train and validation"):
        chronological_split([row("g",1)],validation_start=datetime(2026,1,1,tzinfo=UTC))
