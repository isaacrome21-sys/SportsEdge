"""Synthetic URL authenticity boundary tests; no source is treated as fact."""
import pytest

from sportsedge.dk_evidence_attestation import _safe_https_url, review_attestations
from sportsedge.dk_market_coverage_contract import REQUIRED_EVIDENCE


@pytest.mark.parametrize("url", [
    "https://", "https:///path", "https://user:pass@example.com/x",
    "https://example.com:444/x", "https://example.com:bad/x",
    "https://example.com/x#fragment", "https://example.com\\@attacker.test/x",
    "https://example.com/x\n", " https://example.com/x",
    "http://example.com/x", "https://[invalid/x",
])
def test_malformed_or_ambiguous_urls_refused(url):
    assert _safe_https_url(url) is False


@pytest.mark.parametrize("url", [
    "https://example.com/x", "https://example.com:443/x",
    "https://x.example.org/path?item=1",
])
def test_syntactically_valid_urls_not_source_authentication(url):
    assert _safe_https_url(url) is True


def test_invalid_url_blocks_market_review():
    evidence = {key: {
        "verified": True, "source_url": "https://example.org/evidence",
        "published_at": "2026-10-14T17:00:00Z",
        "observed_at": "2026-10-14T18:00:00Z",
    } for key in REQUIRED_EVIDENCE}
    evidence["pre_event_provenance"]["source_url"] = "https://user@official.example/x"
    result = review_attestations(evidence, cutoff="2026-10-14T19:00:00Z")
    assert "pre_event_provenance" in result["missing_evidence"]
    assert result["play_authorized"] is False
