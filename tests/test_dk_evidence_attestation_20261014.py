"""Synthetic evidence-attestation checks. No live quotes or market promotion."""
import pytest

from sportsedge.dk_evidence_attestation import review_attestations
from sportsedge.dk_market_coverage_contract import REQUIRED_EVIDENCE

CUTOFF = "2026-10-14T19:00:00Z"


def full_evidence():
    return {key: {"verified": True, "source_url": "https://example.org/evidence",
                  "published_at": "2026-10-14T17:00:00Z",
                  "observed_at": "2026-10-14T18:00:00Z"} for key in REQUIRED_EVIDENCE}


def test_complete_still_never_promotes_play():
    result = review_attestations(full_evidence(), cutoff=CUTOFF)
    assert result["status"] == "EVIDENCE_COMPLETE_REVIEW_REQUIRED"
    assert result["play_authorized"] is False


@pytest.mark.parametrize("field,value", [
    ("paired_fresh_quotes", True),
    ("paired_fresh_quotes", {"verified": True}),
    ("paired_fresh_quotes", {"verified": False}),
])
def test_boolean_or_incomplete_attestation_refused(field, value):
    evidence = full_evidence()
    evidence[field] = value
    assert field in review_attestations(evidence, cutoff=CUTOFF)["missing_evidence"]


@pytest.mark.parametrize("change", [
    {"published_at": "2026-10-14T19:01:00Z", "observed_at": "2026-10-14T19:02:00Z"},
    {"observed_at": "2026-10-14T19:01:00Z"},
    {"published_at": "2026-10-14T18:30:00Z", "observed_at": "2026-10-14T18:00:00Z"},
    {"observed_at": "2026-10-14T18:00:00"},
    {"source_url": "http://example.org/evidence"},
])
def test_invalid_or_post_cutoff_evidence_refused(change):
    evidence = full_evidence()
    evidence["pre_event_provenance"].update(change)
    assert "pre_event_provenance" in review_attestations(evidence, cutoff=CUTOFF)["missing_evidence"]


def test_invalid_cutoff_refused():
    with pytest.raises(ValueError, match="INVALID_CUTOFF"):
        review_attestations(full_evidence(), cutoff="2026-10-14T19:00:00")
