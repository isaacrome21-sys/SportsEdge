from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.reconcile_freeze_deltas import assert_refreeze_machine_verified


def test_refrozen_disposition_is_fail_closed_until_full_semantics_are_verified() -> None:
    registry = {
        "bundles": [
            {
                "bundle_id": "BUNDLE_A",
                "disposition": {
                    "state": "REFROZEN",
                    "new_bundle_id": "BUNDLE_A_V2",
                    "new_freeze_sha": "1" * 40,
                    "forward_clock_restart_at": "2026-09-14T14:00:00Z",
                    "prior_bundle_hash": "a" * 64,
                    "new_bundle_hash": "b" * 64,
                    "prior_semantics_invalid_after": "2026-09-14T14:00:00Z",
                    "prior_evidence_invalidation_rule": "HASH_AND_TIME",
                },
            }
        ]
    }
    with pytest.raises(SystemExit, match="REFROZEN_SEMANTICS_NOT_MACHINE_VERIFIED:BUNDLE_A"):
        assert_refreeze_machine_verified(registry)


def test_revoked_disposition_remains_allowed() -> None:
    registry = {
        "bundles": [
            {
                "bundle_id": "BUNDLE_A",
                "disposition": {
                    "state": "REVOKED",
                    "revoked_at": "2026-09-14T14:00:00Z",
                    "prior_forward_clock_invalidated": True,
                },
            }
        ]
    }
    assert_refreeze_machine_verified(registry)


def test_registered_cfb_candidate_prereg_refreeze_is_machine_verified() -> None:
    registry = json.loads(Path("config/freeze_reconciliation_registry_v1.json").read_text())
    bundle = next(
        row
        for row in registry["bundles"]
        if row["bundle_id"] == "CFB_CANDIDATE_PREREG_FREEZE_V1"
    )
    if (bundle.get("disposition") or {}).get("state") != "REFROZEN":
        pytest.skip("candidate prereg refreeze not yet materialized on this branch")
    assert_refreeze_machine_verified(registry)


def test_cfb_candidate_prereg_refreeze_rejects_unbound_freeze_commit() -> None:
    registry = json.loads(Path("config/freeze_reconciliation_registry_v1.json").read_text())
    bundle = next(
        row
        for row in registry["bundles"]
        if row["bundle_id"] == "CFB_CANDIDATE_PREREG_FREEZE_V1"
    )
    if (bundle.get("disposition") or {}).get("state") != "REFROZEN":
        pytest.skip("candidate prereg refreeze not yet materialized on this branch")
    bad = copy.deepcopy(registry)
    bad_bundle = next(
        row
        for row in bad["bundles"]
        if row["bundle_id"] == "CFB_CANDIDATE_PREREG_FREEZE_V1"
    )
    bad_bundle["disposition"]["new_freeze_sha"] = "1" * 40
    with pytest.raises(SystemExit):
        assert_refreeze_machine_verified(bad)
