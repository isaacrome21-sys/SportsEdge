"""Hostile-boundary regression tests for the freeze-reconciliation validator.

Reproductions from the Oct 27, 2026 adversarial pass: malformed registry /
policy shapes crashed _validate_registry and the reconcile entry points
with raw AttributeError / KeyError / ValueError instead of the module's
named FreezeReconciliationError, and a non-mapping authority block crashed
the boundary check instead of failing closed. The real registry and
policy validate and reconcile exactly as before.
"""
from pathlib import Path

import pytest

from sportsedge.governance import freeze_reconciliation as fr

REPO = Path(__file__).resolve().parents[1]
POLICY = fr.load_json(REPO / "config/freeze_reconciliation_policy_v1.json")
REGISTRY = fr.load_json(REPO / "config/freeze_reconciliation_registry_v1.json")
BUNDLE = REGISTRY["bundles"][0]
HEAD = fr.resolve_sha(REPO, "HEAD")


def _refuses(code, policy=None, registry=None):
    with pytest.raises(fr.FreezeReconciliationError, match=code):
        fr._validate_registry(POLICY if policy is None else policy,
                              REGISTRY if registry is None else registry)


def test_real_registry_and_policy_still_validate():
    fr._validate_registry(POLICY, REGISTRY)


def test_non_dict_delta_row_refused():
    _refuses("FREEZE_RECONCILIATION_DELTA_INVALID",
             registry={**REGISTRY, "deltas": ["junk"]})


def test_non_dict_bundle_row_refused():
    _refuses("FREEZE_RECONCILIATION_BUNDLE_ID_MISSING",
             registry={**REGISTRY, "bundles": ["junk"]})


@pytest.mark.parametrize("bad", ["REVOKED", ["REVOKED"], 7])
def test_non_dict_disposition_refused(bad):
    _refuses("FREEZE_RECONCILIATION_DISPOSITION_INVALID",
             registry={**REGISTRY, "bundles": [{**BUNDLE, "disposition": bad}]})


def test_delta_missing_identity_fields_refused():
    _refuses("FREEZE_RECONCILIATION_DELTA_INVALID",
             registry={**REGISTRY, "deltas": [{"pr": 1, "merge_sha": HEAD}]})


@pytest.mark.parametrize("bad_pr", ["2719", True, 27.5, None])
def test_delta_pr_wrong_type_refused(bad_pr):
    _refuses("FREEZE_RECONCILIATION_DELTA_INVALID",
             registry={**REGISTRY,
                       "deltas": [{"delta_id": "X", "pr": bad_pr,
                                   "merge_sha": HEAD}]})


def test_bundle_missing_id_refused():
    bundle = {k: v for k, v in BUNDLE.items() if k != "bundle_id"}
    _refuses("FREEZE_RECONCILIATION_BUNDLE_ID_MISSING",
             registry={**REGISTRY, "bundles": [bundle]})


def test_non_dict_policy_and_registry_refused():
    _refuses("FREEZE_RECONCILIATION_POLICY_SCHEMA_INVALID", policy=["x"])
    _refuses("FREEZE_RECONCILIATION_REGISTRY_SCHEMA_INVALID", registry=["x"])


def test_non_dict_authority_refused():
    _refuses("FREEZE_POLICY_AUTHORITY_INVALID",
             policy={**POLICY, "authority": ["x"]})


def test_boundary_check_fails_closed_on_malformed_authority():
    assert fr.main_matches_reconciliation_boundary(
        REPO, policy={**POLICY, "authority": ["x"]}, registry=REGISTRY,
        reconciled_through_sha=str(REGISTRY["reconciled_through_sha"]),
        current_main_ref="HEAD") is False


@pytest.mark.parametrize("delta", [{"pr": 1, "merge_sha": HEAD},
                                   {"delta_id": "X", "pr": "abc",
                                    "merge_sha": HEAD},
                                   {"delta_id": "X", "pr": 1},
                                   "junk"])
def test_reconcile_entry_point_refuses_malformed_delta(delta):
    with pytest.raises(fr.FreezeReconciliationError,
                       match="FREEZE_RECONCILIATION_DELTA_INVALID"):
        fr.reconcile_delta_bundle(REPO, delta, BUNDLE)
