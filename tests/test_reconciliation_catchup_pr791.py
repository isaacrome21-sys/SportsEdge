from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_reconciliation_registry_view import merge_view
from sportsedge.governance.reconciliation_content_identity import boundary_matches

OLD_BOUNDARY = "f8afb5c5e3251b6ede8a39ef25c47fdd07dfb7ee"
PRE_791 = "6aa3edfa33e13e0b81d57586e1600ec5b5d17ccb"
PR_791 = "9a4f81a6a2a2eaf3c77c1ff9f0510f99a3a3a170"


def test_intervening_reconciliation_merge_before_pr791_is_governed_content_neutral() -> None:
    registry = json.loads(Path("config/freeze_reconciliation_registry_v1.json").read_text())
    matched, detail = boundary_matches(
        Path.cwd(),
        registry=registry,
        registered_ref=OLD_BOUNDARY,
        current_ref=PRE_791,
    )
    assert matched is True, detail
    assert detail["ancestry_ok"] is True
    assert detail["content_identity_ok"] is True


def test_pr791_is_registered_as_conservative_cfb_candidate_prereg_refreeze() -> None:
    registry = json.loads(Path("config/freeze_reconciliation_registry_v1.json").read_text())
    assert registry["reconciled_through_sha"] == PR_791
    assert registry["deltas"][-1]["merge_sha"] == PR_791
    assert registry["deltas"][-1]["pr"] == 791
    bundle = next(row for row in registry["bundles"] if row["bundle_id"] == "CFB_CANDIDATE_PREREG_FREEZE_V1")
    disposition = bundle["disposition"]
    assert disposition["state"] == "REFROZEN"
    assert disposition["new_bundle_id"] == "CFB_CANDIDATE_PREREG_FREEZE_V2"
    assert disposition["new_freeze_sha"] == PR_791
    assert disposition["forward_clock_restart_at"] == "2026-09-17T00:24:27Z"
    assert "ATTEMPT_COUNT_REMAINS_ZERO" in disposition["reason"]


def test_registered_candidate_prereg_refreeze_supersedes_only_stale_extension_revocation() -> None:
    policy = json.loads(Path("config/freeze_inventory_policy_v1.json").read_text())
    registry = json.loads(Path("config/freeze_reconciliation_registry_v1.json").read_text())
    extension = json.loads(Path("config/reconciliation_coverage_v1.json").read_text())

    _, effective, attestation = merge_view(policy, registry, extension)
    bundle = next(row for row in effective["bundles"] if row["bundle_id"] == "CFB_CANDIDATE_PREREG_FREEZE_V1")
    assert bundle["disposition"]["state"] == "REFROZEN"
    assert "CFB_CANDIDATE_PREREG_FREEZE_V1" in attestation["superseded_extension_revocations"]

    bad = json.loads(json.dumps(registry))
    bad_bundle = next(row for row in bad["bundles"] if row["bundle_id"] == "CFB_CANDIDATE_PREREG_FREEZE_V1")
    bad_bundle["disposition"] = {"state": "ACTIVE"}
    with pytest.raises(SystemExit, match="BUNDLE_DISPOSITION_CONFLICT:CFB_CANDIDATE_PREREG_FREEZE_V1"):
        merge_view(policy, bad, extension)
