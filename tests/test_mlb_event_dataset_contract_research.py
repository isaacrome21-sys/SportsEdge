import pytest
from research.mlb_event_dataset_contract import validate_events

CUT="2026-01-01T00:00:00Z"
def event(**overrides):
    row=dict(event_id="g1-p1",player_id="p1",outcome=1,
             event_time="2026-01-02T00:00:00Z",
             observed_at="2025-12-31T23:00:00Z",
             source_url="https://example.org/fixture")
    row.update(overrides)
    return row

def test_structural_validation_not_authentication():
    r=validate_events([event()],training_cutoff=CUT)
    assert r["schema_valid"] and not r["source_authenticity_verified"]
    assert not r["play_authorized"]

@pytest.mark.parametrize("change",[
    {"outcome":2},{"observed_at":"2026-01-03T00:00:00Z"},
    {"event_time":"2025-12-31T00:00:00Z"},
    {"source_url":"http://example.org/fixture"},
    {"event_id":""},{"player_id":True},
])
def test_bad_event_refused(change):
    with pytest.raises(ValueError):
        validate_events([event(**change)],training_cutoff=CUT)

def test_duplicate_refused():
    with pytest.raises(ValueError,match="DUPLICATE"):
        validate_events([event(),event(event_time="2026-01-03T00:00:00Z")],training_cutoff=CUT)
