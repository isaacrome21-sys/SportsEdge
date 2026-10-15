"""Malformed source claims must fail closed, never crash or authorize pricing."""
import pytest
from sportsedge.mlb_starter_source_audit import audit_starter_sources

BASE = dict(game_id="fixture-1", team_id=108, source_kind="OFFICIAL_LEAGUE",
            assertion="NAMED", pitcher_id=1234,
            source_url="https://www.mlb.com/news/fixture-only",
            source_snapshot_sha256="a" * 64,
            published_at="2026-10-15T16:00:00Z",
            observed_at="2026-10-15T16:01:00Z")

@pytest.mark.parametrize("field,value", [
    ("source_kind", []), ("source_kind", {}), ("source_kind", 1),
    ("assertion", []), ("assertion", {}), ("assertion", 1),
    ("source_url", []), ("source_url", {}), ("source_url", 1),
    ("source_url", None), ("source_kind", None), ("assertion", None),
])
def test_malformed_claim_fails_closed(field, value):
    row = dict(BASE, **{field: value})
    result = audit_starter_sources([row], game_id="fixture-1", team_id=108,
        cutoff="2026-10-15T17:00:00Z", first_pitch="2026-10-15T19:00:00Z")
    assert result["status"] == "INVALID_EVIDENCE"
    assert result["rejected_sources"][0]["reason"] == "INVALID_SOURCE_CLAIM"
    assert not result["starter_binding_eligible"]
    assert not result["market_probability_verified"]
    assert not result["play_authorized"]
