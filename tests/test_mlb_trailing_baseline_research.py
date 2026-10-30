import pytest
from research.mlb_trailing_baseline import evaluate

def test_prequential_no_play():
    rows=[("2026-01-01T00:00:00Z","a",1),("2026-01-02T00:00:00Z","a",0)]
    r=evaluate(rows,window=2)
    assert r["n"]==2 and not r["play_authorized"] and not r["market_probability_verified"]

def test_reject_reverse_order():
    rows=[("2026-01-02T00:00:00Z","a",1),("2026-01-01T00:00:00Z","a",0)]
    with pytest.raises(ValueError,match="NON_CHRONOLOGICAL"):
        evaluate(rows)
