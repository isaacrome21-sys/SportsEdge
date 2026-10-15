"""Research-only synthetic invariants for source-evidence audit."""
from research.pit_source_evidence_audit import audit_evidence


def test_unverified_claim_never_authorizes_runtime():
    record = {
        "event_id": "synthetic-game", "subject_id": "synthetic-player",
        "fact_type": "starter", "source_url": "https://www.mlb.com/news/example",
        "source_class": "official_league", "status": "STARTER",
        "published_at": "2026-10-15T15:00:00-05:00",
        "observed_at": "2026-10-15T15:01:00-05:00",
    }
    result = audit_evidence(
        [record], event_id="synthetic-game", subject_id="synthetic-player",
        fact_type="starter", as_of="2026-10-15T16:00:00-05:00",
        pre_event_cutoff="2026-10-15T19:00:00-05:00",
        fresh_after="2026-10-15T12:00:00-05:00")
    assert result["candidate_status"] == "STARTER"
    assert result["operational_status"] == "UNKNOWN/BLOCKED"
    assert result["runtime_admission_authorized"] is False
    assert result["play_authorized"] is False
