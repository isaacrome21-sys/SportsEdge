import pytest
from research.mlb_event_dataset_contract import validate_events

CUT="2026-01-01T00:00:00Z"
def event(**overrides):
    row=dict(event_id="g1-p1",player_id="p1",outcome=1,
             event_time="2026-01-02T00:00:00Z",
             prediction_observed_at="2026-01-01T23:00:00Z",
             outcome_observed_at="2026-01-02T04:00:00Z",
             source_url="https://example.org/fixture")
    row.update(overrides)
    return row

def test_post_cutoff_prediction_is_valid_but_unverified():
    r=validate_events([event()],training_cutoff=CUT)
    assert r["schema_valid"] and not r["source_authenticity_verified"]
    assert not r["prediction_provenance_verified"] and not r["play_authorized"]

@pytest.mark.parametrize("change",[
    {"outcome":2},
    {"prediction_observed_at":"2026-01-02T00:00:00Z"},
    {"prediction_observed_at":"2026-01-03T00:00:00Z"},
    {"outcome_observed_at":"2026-01-01T23:00:00Z"},
    {"event_time":"2025-12-31T00:00:00Z"},
    {"source_url":"http://example.org/fixture"},
    {"source_url":"https://"},
    {"event_id":""},{"player_id":True},
])
def test_bad_event_refused(change):
    with pytest.raises(ValueError):
        validate_events([event(**change)],training_cutoff=CUT)

def test_duplicate_refused():
    with pytest.raises(ValueError,match="DUPLICATE"):
        validate_events([event(),event(event_time="2026-01-03T00:00:00Z", outcome_observed_at="2026-01-03T04:00:00Z")],training_cutoff=CUT)

def test_missing_timing_fields_refused():
    row=event()
    del row["prediction_observed_at"]
    with pytest.raises(ValueError,match="INVALID_TIMESTAMP"):
        validate_events([row],training_cutoff=CUT)
