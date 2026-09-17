from __future__ import annotations

import json
from pathlib import Path

from scripts.build_reconciliation_registry_view import merge_view

PR_806 = "a16bc6907e95267e919f42d15b04afaebcf5bb8c"
PR_803 = "7d64c5e6b149324e54286f29b7058b696886749b"
BUNDLE_ID = "MARKET_MAKER_RADAR_EVIDENCE_FREEZE_V2"
PR803_GOVERNED_PATHS = {
    ".github/workflows/market-maker-radar.yml",
    "config/market_maker_radar_v1.json",
    "docs/market_maker_radar.md",
    "scripts/capture_market_maker_fourc_line_history.py",
    "tests/test_import_fourc_line_history.py",
}


def _covered(bundle: dict, path: str) -> bool:
    if path in set(bundle.get("coverage_paths") or []):
        return True
    return any(path.startswith(prefix) for prefix in (bundle.get("coverage_prefixes") or []))


def test_reconciliation_boundary_advances_through_pr803_in_first_parent_order() -> None:
    registry = json.loads(Path("config/freeze_reconciliation_registry_v1.json").read_text())
    assert registry["reconciled_through_sha"] == PR_803
    tail = registry["deltas"][-2:]
    assert [(row["pr"], row["merge_sha"]) for row in tail] == [
        (806, PR_806),
        (803, PR_803),
    ]


def test_pr803_market_radar_surfaces_are_all_governed() -> None:
    registry = json.loads(Path("config/freeze_reconciliation_registry_v1.json").read_text())
    bundle = next(row for row in registry["bundles"] if row["bundle_id"] == BUNDLE_ID)
    missing = sorted(path for path in PR803_GOVERNED_PATHS if not _covered(bundle, path))
    assert missing == []


def test_effective_market_radar_bundle_remains_fail_closed_revoked() -> None:
    policy = json.loads(Path("config/freeze_inventory_policy_v1.json").read_text())
    registry = json.loads(Path("config/freeze_reconciliation_registry_v1.json").read_text())
    extension = json.loads(Path("config/reconciliation_coverage_v1.json").read_text())

    _, effective, _ = merge_view(policy, registry, extension)
    bundle = next(row for row in effective["bundles"] if row["bundle_id"] == BUNDLE_ID)
    disposition = bundle["disposition"]
    assert disposition["state"] == "REVOKED"
    assert disposition["revoked_at"] == "2026-09-14T17:10:32Z"
    assert disposition["prior_forward_clock_invalidated"] is True
    assert disposition["reason"] == "CONFIRMED_DRIFT_REVOKED_PENDING_STABLE_MAIN_REFREEZE"
