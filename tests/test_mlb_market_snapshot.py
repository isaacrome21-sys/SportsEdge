from datetime import datetime, timezone

import pytest

from sportsedge.mlb_market_snapshot import DEFAULT_MARKETS, MLBMarketSnapshotError, build_market_snapshot, snapshot_path
from sportsedge.mlb_validation_dashboard import build_dashboard_row


def _row(market):
    return build_dashboard_row(market=market, rows=[], predictive_status="Insufficient Evidence",
        infrastructure_status="Unknown", model_sha="model", feature_sha="feature",
        last_durable_evidence_timestamp=None, uncertainty_enabled=False,
        gate_evaluator_sha="gate")


def test_snapshot_is_immutable_complete_and_hashed():
    s = build_market_snapshot(rows=[_row(m) for m in DEFAULT_MARKETS], git_sha="git", branch="research",
        evaluator_sha="eval", model_sha="model", feature_sha="feature",
        snapshot_timestamp=datetime(2026, 8, 21, 22, 45, tzinfo=timezone.utc))
    assert s.is_immutable is True
    assert len(s.markets) == len(DEFAULT_MARKETS)
    assert len(s.content_sha256) == 64
    assert s.snapshot_id == "research-2026-08-21T22:45:00Z"


def test_snapshot_allows_null_research_metrics():
    s = build_market_snapshot(rows=[_row(m) for m in DEFAULT_MARKETS], git_sha="g", branch="r",
        evaluator_sha="e", model_sha="m", feature_sha="f")
    assert all(row["gate_quality_score"] is None for row in s.markets)


def test_snapshot_requires_all_target_markets():
    with pytest.raises(MLBMarketSnapshotError):
        build_market_snapshot(rows=[_row("NRFI")], git_sha="g", branch="r", evaluator_sha="e",
                              model_sha="m", feature_sha="f")


def test_snapshot_path_is_versioned_not_latest_overwrite():
    s = build_market_snapshot(rows=[_row(m) for m in DEFAULT_MARKETS], git_sha="g", branch="r",
        evaluator_sha="e", model_sha="m", feature_sha="f",
        snapshot_timestamp=datetime(2026, 8, 21, 22, 45, tzinfo=timezone.utc))
    p = snapshot_path(s)
    assert "validation_snapshots" in p
    assert "latest" not in p.lower()
    assert s.content_sha256[:12] in p
