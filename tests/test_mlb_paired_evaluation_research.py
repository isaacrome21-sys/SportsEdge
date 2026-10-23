import pytest
from research.mlb_paired_evaluation import paired_evaluate

CUT="2026-01-01T00:00:00Z"
def row(t, **kw):
    return dict(event_time=t, outcome=1, challenger=.6, league=.5, trailing=.4, **kw)

def test_paired_metrics_unverified():
    r=paired_evaluate([row("2026-01-02T00:00:00Z")],train_cutoff=CUT)
    assert r["n"]==1 and not r["market_probability_verified"] and not r["play_authorized"]

def test_overlap_refused():
    with pytest.raises(ValueError,match="NON_CHRONOLOGICAL"):
        paired_evaluate([row(CUT)],train_cutoff=CUT)

def test_missing_prediction_refused():
    bad=row("2026-01-02T00:00:00Z")
    del bad["trailing"]
    with pytest.raises(ValueError,match="MISSING_OR_INVALID"):
        paired_evaluate([bad],train_cutoff=CUT)

def test_same_timestamp_refused():
    t="2026-01-02T00:00:00Z"
    with pytest.raises(ValueError,match="NON_CHRONOLOGICAL"):
        paired_evaluate([row(t),row(t)],train_cutoff=CUT)
