import pytest
from sportsedge.sports.nhl.history import NHLHistoricalGame,training_rows,dataset_sha256,NHLTrainingProvenance

def game(**kw):
    base=dict(game_id="g1",season="2026",puck_drop="2026-10-10T00:00:00Z",captured_at="2026-10-09T20:00:00Z",home_team="A",away_team="B",source="fixture",source_version="v1",features={"xgf60":3.1})
    base.update(kw); return NHLHistoricalGame(**base)

def test_rejects_post_drop_feature_capture():
    with pytest.raises(ValueError): game(captured_at="2026-10-10T00:01:00Z")

def test_targets_require_postgame_settlement():
    with pytest.raises(ValueError): game(home_regulation_goals=3,away_regulation_goals=2)
    assert game(home_regulation_goals=3,away_regulation_goals=2,settled_at="2026-10-10T03:00:00Z")

def test_temporal_training_cutoff_and_hash_are_deterministic():
    old=game(home_regulation_goals=3,away_regulation_goals=2,settled_at="2026-10-10T03:00:00Z")
    future=game(game_id="g2",puck_drop="2026-10-20T00:00:00Z",captured_at="2026-10-19T20:00:00Z",home_regulation_goals=2,away_regulation_goals=1,settled_at="2026-10-20T03:00:00Z")
    assert training_rows([future,old],"2026-10-15T00:00:00Z")==[old]
    assert dataset_sha256([future,old])==dataset_sha256([old,future])

def test_training_provenance_requires_explicit_versions():
    with pytest.raises(ValueError): NHLTrainingProvenance("m1","s1","2026-10-15T00:00:00Z","","abc","none")
