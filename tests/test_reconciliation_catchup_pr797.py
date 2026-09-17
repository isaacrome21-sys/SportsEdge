from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_reconciliation_registry_view import merge_view
from sportsedge.governance.reconciliation_content_identity import boundary_matches

OLD_BOUNDARY = "2930583ee1bac7a94644fe182278212ffe728452"
PRE_797 = "aca9b0cb4a2c13da13307c2fc7a6be54a50699ca"
PR_797 = "f8afb5c5e3251b6ede8a39ef25c47fdd07dfb7ee"


def test_intervening_main_before_pr797_is_governed_content_neutral() -> None:
    registry = json.loads(Path("config/freeze_reconciliation_registry_v1.json").read_text())
    matched, detail = boundary_matches(
        Path.cwd(),
        registry=registry,
        registered_ref=OLD_BOUNDARY,
        current_ref=PRE_797,
    )
    assert matched is True, detail
    assert detail["ancestry_ok"] is True
    assert detail["content_identity_ok"] is True


def test_pr797_is_registered_as_conservative_cfb_refreeze() -> None:
    registry = json.loads(Path("config/freeze_reconciliation_registry_v1.json").read_text())
    assert any(delta["merge_sha"] == PR_797 for delta in registry["deltas"])
    bundle = next(row for row in registry["bundles"] if row["bundle_id"] == "CFB_PROP_MODEL_FREEZE_V1")
    disposition = bundle["disposition"]
    assert disposition["state"] == "REFROZEN"
    assert disposition["new_bundle_id"] == "CFB_PROP_MODEL_FREEZE_V2"
    assert disposition["new_freeze_sha"] == PR_797
    assert disposition["forward_clock_restart_at"] == "2026-09-16T23:23:45Z"


def test_registered_refreezes_supersede_only_stale_extension_revocations() -> None:
    policy = json.loads(Path("config/freeze_inventory_policy_v1.json").read_text())
    registry = json.loads(Path("config/freeze_reconciliation_registry_v1.json").read_text())
    extension = json.loads(Path("config/reconciliation_coverage_v1.json").read_text())

    _, effective, attestation = merge_view(policy, registry, extension)
    bundle = next(row for row in effective["bundles"] if row["bundle_id"] == "CFB_PROP_MODEL_FREEZE_V1")
    assert bundle["disposition"]["state"] == "REFROZEN"
    superseded = attestation["superseded_extension_revocations"]
    assert "CFB_PROP_MODEL_FREEZE_V1" in superseded
    assert set(superseded).issubset({
        "CFB_PROP_MODEL_FREEZE_V1",
        "CFB_CANDIDATE_PREREG_FREEZE_V1",
    })

    bad = json.loads(json.dumps(registry))
    bad_bundle = next(row for row in bad["bundles"] if row["bundle_id"] == "CFB_PROP_MODEL_FREEZE_V1")
    bad_bundle["disposition"] = {"state": "ACTIVE"}
    with pytest.raises(SystemExit, match="BUNDLE_DISPOSITION_CONFLICT:CFB_PROP_MODEL_FREEZE_V1"):
        merge_view(policy, bad, extension)
