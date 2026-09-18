from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_reconciliation_registry_view import merge_view
from sportsedge.governance.reconciliation_content_identity import boundary_matches

OLD_BOUNDARY = "f8afb5c5e3251b6ede8a39ef25c47fdd07dfb7ee"
PRE_791 = "6aa3edfa33e13e0b81d57586e1600ec5b5d17ccb"
PR_791 = "9a4f81a6a2a2eaf3c77c1ff9f0510f99a3a3a170"
REFREEZE_SHA = "0e24934bb6787e2d9ffe1cbb377f128fb2e7dfc9"


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


def test_pr791_candidate_prereg_is_machine_verified_refrozen_at_current_main_boundary() -> None:
    registry = json.loads(Path("config/freeze_reconciliation_registry_v1.json").read_text())
    delta = next(row for row in registry["deltas"] if row["merge_sha"] == PR_791)
    assert delta["pr"] == 791
    bundle = next(row for row in registry["bundles"] if row["bundle_id"] == "CFB_CANDIDATE_PREREG_FREEZE_V1")
    disposition = bundle["disposition"]
    assert disposition["state"] == "REFROZEN"
    assert disposition["verification_schema"] == "CFB_CANDIDATE_PREREG_REFREEZE_V1"
    assert disposition["prior_bundle_freeze_sha"] == bundle["freeze_sha"]
    assert disposition["trigger_delta_sha"] == PR_791
    assert disposition["new_bundle_id"] == "CFB_CANDIDATE_PREREG_FREEZE_V2"
    assert disposition["new_freeze_sha"] == REFREEZE_SHA
    assert disposition["forward_clock_restart_at"] == "2026-09-18T03:31:14Z"
    assert disposition["row_admissibility_semantics"] == "PREREGISTRATION_ONLY_NO_EVALUATION_ROWS_V1"
    assert disposition["selection_scope_only"] is True
    assert all(value is False for value in disposition["authority"].values())


def test_registered_candidate_prereg_refreeze_supersedes_older_extension_revocation() -> None:
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
