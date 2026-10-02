import pytest
from sportsedge.nfl_scoring_composition_artifact import (
    ScoringCompositionArtifactError,dump_prior,load_prior,
)
from sportsedge.nfl_scoring_composition_fit import ScoringCompositionPrior

def _prior():
    return ScoringCompositionPrior(
        as_of="2026-09-01T00:00:00+00:00",training_rows=3,
        counts_by_score={7:{(1,1,0,0,0):2},10:{(1,1,0,1,0):1}},
    )

def test_scoring_prior_round_trip_is_hash_bound():
    payload=dump_prior(_prior())
    restored=load_prior(payload)
    assert restored==_prior()
    assert len(payload["artifact_sha256"])==64
    assert payload["market_inputs_used"] is False

def test_scoring_prior_tamper_fails_closed():
    payload=dump_prior(_prior())
    payload["training_rows"]=4
    with pytest.raises(ScoringCompositionArtifactError,match="HASH_MISMATCH"):
        load_prior(payload)

def test_scoring_prior_market_authority_cannot_be_injected():
    payload=dump_prior(_prior())
    payload["market_inputs_used"]=True
    with pytest.raises(ScoringCompositionArtifactError,match="HASH_MISMATCH"):
        load_prior(payload)
