from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol, Sequence

from sportsedge.mlb_market_snapshot import DEFAULT_MARKETS, build_market_snapshot
from sportsedge.mlb_snapshot_store import SnapshotArtifact, write_snapshot
from sportsedge.mlb_validation_dashboard import MLBValidationDashboardRow


class InsufficientDurableEvidence(RuntimeError):
    pass


@dataclass(frozen=True)
class DurableMarketEvidence:
    market: str
    opportunities: tuple[Mapping[str, Any], ...]
    predictive_status: str
    infrastructure_status: str
    last_durable_evidence_timestamp: str | None
    metrics: Mapping[str, Any]


@dataclass(frozen=True)
class SnapshotProvenance:
    git_sha: str
    branch: str
    evaluator_sha: str
    model_sha: str
    feature_sha: str
    uncertainty_sha: str | None = None
    gate_evaluator_sha: str | None = None
    notes: str | None = None


class DurableEvidenceSource(Protocol):
    def load_market(self, market: str) -> DurableMarketEvidence | None: ...


DashboardBuilder = Callable[[DurableMarketEvidence, SnapshotProvenance], MLBValidationDashboardRow]


def ingest_research_snapshot(*, evidence_source: DurableEvidenceSource,
                             dashboard_builder: DashboardBuilder,
                             provenance: SnapshotProvenance,
                             root: str,
                             markets: Sequence[str] = DEFAULT_MARKETS,
                             snapshot_timestamp: datetime | None = None) -> SnapshotArtifact | None:
    """Research-only orchestration from durable evidence to immutable snapshot.

    Missing markets may be represented only when the evidence source itself returns a
    durable market record whose status/metrics express insufficiency. The adapter never
    invents placeholder evidence. If no requested market has durable evidence, no write occurs.
    """
    evidence: list[DurableMarketEvidence] = []
    missing: list[str] = []
    for market in markets:
        item = evidence_source.load_market(market)
        if item is None:
            missing.append(market)
        else:
            evidence.append(item)

    if not evidence:
        return None

    # Complete snapshot coverage requires durable source records for every requested market.
    # Partial numerical evidence is fine; absent source records are not fabricated.
    if missing:
        raise InsufficientDurableEvidence("missing durable market records: " + ",".join(missing))

    rows = [dashboard_builder(item, provenance) for item in evidence]
    ts = snapshot_timestamp or datetime.now(timezone.utc)
    snapshot = build_market_snapshot(
        rows=rows,
        git_sha=provenance.git_sha,
        branch=provenance.branch,
        evaluator_sha=provenance.evaluator_sha,
        model_sha=provenance.model_sha,
        feature_sha=provenance.feature_sha,
        snapshot_timestamp=ts,
        notes=provenance.notes,
        required_markets=markets,
    )
    return write_snapshot(snapshot, root=root)
