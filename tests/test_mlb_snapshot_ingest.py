from datetime import datetime, timezone

import pytest

from sportsedge.mlb_market_snapshot import DEFAULT_MARKETS
from sportsedge.mlb_snapshot_ingest import DurableMarketEvidence, InsufficientDurableEvidence, SnapshotProvenance, ingest_research_snapshot
from sportsedge.mlb_snapshot_store import list_snapshots
from sportsedge.mlb_validation_dashboard import build_dashboard_row


class Source:
    def __init__(self, data): self.data = data
    def load_market(self, market): return self.data.get(market)


def evidence(market, opportunities=()):
    return DurableMarketEvidence(market, tuple(opportunities), "Insufficient Evidence", "Healthy", None, {})


def builder(item, provenance):
    return build_dashboard_row(market=item.market, rows=item.opportunities,
        predictive_status=item.predictive_status, infrastructure_status=item.infrastructure_status,
        model_sha=provenance.model_sha, feature_sha=provenance.feature_sha,
        last_durable_evidence_timestamp=item.last_durable_evidence_timestamp,
        uncertainty_enabled=False, uncertainty_sha=provenance.uncertainty_sha,
        gate_evaluator_sha=provenance.gate_evaluator_sha)


def prov():
    return SnapshotProvenance("git", "research", "eval", "model", "feature", gate_evaluator_sha="gate")


def test_complete_durable_evidence_writes_snapshot(tmp_path):
    source = Source({m: evidence(m) for m in DEFAULT_MARKETS})
    artifact = ingest_research_snapshot(evidence_source=source, dashboard_builder=builder,
        provenance=prov(), root=str(tmp_path), snapshot_timestamp=datetime(2026,8,21,22,45,tzinfo=timezone.utc))
    assert artifact is not None
    assert len(list_snapshots(root=tmp_path)) == 1


def test_partial_numeric_evidence_still_snapshots_when_every_market_has_durable_record(tmp_path):
    data = {m: evidence(m) for m in DEFAULT_MARKETS}
    data["NRFI"] = evidence("NRFI", [{"gate_decision":"PASS","outcome":"LOSS","clv":None}])
    artifact = ingest_research_snapshot(evidence_source=Source(data), dashboard_builder=builder,
        provenance=prov(), root=str(tmp_path))
    assert artifact is not None


def test_no_durable_evidence_returns_none_and_writes_nothing(tmp_path):
    artifact = ingest_research_snapshot(evidence_source=Source({}), dashboard_builder=builder,
        provenance=prov(), root=str(tmp_path))
    assert artifact is None
    assert list_snapshots(root=tmp_path) == []


def test_missing_market_record_is_not_fabricated(tmp_path):
    data = {m: evidence(m) for m in DEFAULT_MARKETS if m != "HOME_RUN"}
    with pytest.raises(InsufficientDurableEvidence):
        ingest_research_snapshot(evidence_source=Source(data), dashboard_builder=builder,
            provenance=prov(), root=str(tmp_path))
    assert list_snapshots(root=tmp_path) == []


def test_same_inputs_and_timestamp_have_stable_content_hash(tmp_path):
    ts = datetime(2026,8,21,22,45,tzinfo=timezone.utc)
    data = {m: evidence(m) for m in DEFAULT_MARKETS}
    a = ingest_research_snapshot(evidence_source=Source(data), dashboard_builder=builder,
        provenance=prov(), root=str(tmp_path / "a"), snapshot_timestamp=ts)
    b = ingest_research_snapshot(evidence_source=Source(data), dashboard_builder=builder,
        provenance=prov(), root=str(tmp_path / "b"), snapshot_timestamp=ts)
    assert a.content_hash == b.content_hash
