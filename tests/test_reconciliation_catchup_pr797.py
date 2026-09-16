from __future__ import annotations

import json
from pathlib import Path

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
    assert registry["reconciled_through_sha"] == PR_797
    assert registry["deltas"][-1]["merge_sha"] == PR_797
    bundle = next(row for row in registry["bundles"] if row["bundle_id"] == "CFB_PROP_MODEL_FREEZE_V1")
    disposition = bundle["disposition"]
    assert disposition["state"] == "REFROZEN"
    assert disposition["new_bundle_id"] == "CFB_PROP_MODEL_FREEZE_V2"
    assert disposition["new_freeze_sha"] == PR_797
    assert disposition["forward_clock_restart_at"] == "2026-09-16T23:23:45Z"
