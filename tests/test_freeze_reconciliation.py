from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from sportsedge.governance.freeze_reconciliation import (
    FreezeReconciliationError,
    build_reconciliation_report,
    main_matches_reconciliation_boundary,
    reconcile_delta_bundle,
)
from sportsedge.governance.reconciliation_content_identity import governed_surface_digest


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return proc.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def repo(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "SportsEdge Test")
    (root / "policy").mkdir()
    (root / "policy" / "freeze.txt").write_text("v1\n", encoding="utf-8")
    (root / "other.txt").write_text("base\n", encoding="utf-8")
    baseline = _commit(root, "baseline")

    (root / "other.txt").write_text("irrelevant\n", encoding="utf-8")
    irrelevant = _commit(root, "irrelevant delta")

    (root / "policy" / "freeze.txt").write_text("v2\n", encoding="utf-8")
    drift = _commit(root, "covered drift")

    (root / "policy" / "new.txt").write_text("new covered file\n", encoding="utf-8")
    inventory_drift = _commit(root, "covered inventory drift")
    return {
        "root": root,
        "baseline": baseline,
        "irrelevant": irrelevant,
        "drift": drift,
        "inventory_drift": inventory_drift,
    }


def _bundle(freeze_sha: str, *, disposition=None) -> dict[str, object]:
    return {
        "bundle_id": "BUNDLE_A",
        "freeze_sha": freeze_sha,
        "coverage_prefixes": ["policy/"],
        "disposition": disposition,
    }


def _delta(name: str, sha: str, pr: int) -> dict[str, object]:
    return {"delta_id": name, "merge_sha": sha, "pr": pr}


def _policy() -> dict[str, object]:
    return {
        "schema": "SPORTSEDGE_FREEZE_RECONCILIATION_POLICY_V1",
        "issue": 686,
        "status": "ACTIVE_BLOCKED",
        "main_merge_hold": "UNCONDITIONAL",
        "authority": {
            "model_p": False,
            "truth_gate": False,
            "promotion": False,
            "staking": False,
            "official": False,
            "validation_attempt": False,
            "untouched_readout": False,
        },
    }


def test_delta_is_adjudicated_separately_per_bundle(repo: dict[str, object]) -> None:
    root = repo["root"]
    baseline = str(repo["baseline"])
    irrelevant = reconcile_delta_bundle(
        root, _delta("IRRELEVANT", str(repo["irrelevant"]), 1), _bundle(baseline)
    )
    drift = reconcile_delta_bundle(
        root, _delta("DRIFT", str(repo["drift"]), 2), _bundle(baseline)
    )
    assert irrelevant.outcome == "NOT_APPLICABLE"
    assert irrelevant.reason == "NO_COVERED_PATH_INTERSECTION"
    assert drift.outcome == "DRIFT_CONFIRMED"
    assert drift.before_bundle_sha256 != drift.after_bundle_sha256
    assert drift.delta_id != irrelevant.delta_id


def test_new_file_inside_covered_bundle_is_drift_confirmed(repo: dict[str, object]) -> None:
    row = reconcile_delta_bundle(
        repo["root"],
        _delta("INVENTORY", str(repo["inventory_drift"]), 3),
        _bundle(str(repo["baseline"])),
    )
    assert row.outcome == "DRIFT_CONFIRMED"
    assert "policy/new.txt" in row.covered_changed_paths


def test_delta_already_present_at_freeze_is_temporally_not_applicable(repo: dict[str, object]) -> None:
    row = reconcile_delta_bundle(
        repo["root"],
        _delta("OLD", str(repo["irrelevant"]), 1),
        _bundle(str(repo["drift"])),
    )
    assert row.outcome == "NOT_APPLICABLE"
    assert row.reason == "DELTA_ALREADY_INCLUDED_IN_BUNDLE_FREEZE"


def test_prehold_drift_from_freeze_to_baseline_is_not_skipped(repo: dict[str, object]) -> None:
    registry = {
        "schema": "SPORTSEDGE_FREEZE_RECONCILIATION_REGISTRY_V1",
        "baseline_main_sha": repo["drift"],
        "reconciled_through_sha": repo["inventory_drift"],
        "bundle_inventory_complete": True,
        "deltas": [_delta("POST_HOLD", str(repo["inventory_drift"]), 3)],
        "bundles": [_bundle(str(repo["baseline"]))],
    }
    report = build_reconciliation_report(
        repo=repo["root"],
        policy=_policy(),
        registry=registry,
        current_main_ref=str(repo["inventory_drift"]),
    )
    prehold = [row for row in report["rows"] if row["delta_id"] == "PREHOLD_BASELINE"]
    assert len(prehold) == 1
    assert prehold[0]["outcome"] == "DRIFT_CONFIRMED"
    assert prehold[0]["reason"] == "COVERED_BUNDLE_DRIFT_BEFORE_HOLD_BASELINE"
    assert "policy/freeze.txt" in prehold[0]["covered_changed_paths"]
    assert report["outcome_counts"]["DRIFT_CONFIRMED"] == 2
    assert "DRIFT_DISPOSITION_REQUIRED:BUNDLE_A" in report["release_blocks"]


def test_confirmed_drift_requires_refreeze_or_revocation(repo: dict[str, object]) -> None:
    root = repo["root"]
    registry = {
        "schema": "SPORTSEDGE_FREEZE_RECONCILIATION_REGISTRY_V1",
        "baseline_main_sha": repo["baseline"],
        "reconciled_through_sha": repo["drift"],
        "bundle_inventory_complete": True,
        "deltas": [_delta("DRIFT", str(repo["drift"]), 2)],
        "bundles": [_bundle(str(repo["baseline"]))],
    }
    report = build_reconciliation_report(
        repo=root,
        policy=_policy(),
        registry=registry,
        current_main_ref=str(repo["drift"]),
    )
    assert report["outcome_counts"]["DRIFT_CONFIRMED"] == 1
    assert report["release_ready"] is False
    assert "DRIFT_DISPOSITION_REQUIRED:BUNDLE_A" in report["release_blocks"]


def test_refreeze_requires_new_sha_and_forward_clock_restart(repo: dict[str, object]) -> None:
    root = repo["root"]
    bad = _bundle(
        str(repo["baseline"]),
        disposition={"state": "REFROZEN", "new_bundle_id": "BUNDLE_A_V2"},
    )
    registry = {
        "schema": "SPORTSEDGE_FREEZE_RECONCILIATION_REGISTRY_V1",
        "baseline_main_sha": repo["baseline"],
        "reconciled_through_sha": repo["drift"],
        "bundle_inventory_complete": True,
        "deltas": [_delta("DRIFT", str(repo["drift"]), 2)],
        "bundles": [bad],
    }
    report = build_reconciliation_report(
        repo=root, policy=_policy(), registry=registry, current_main_ref=str(repo["drift"])
    )
    assert any(block.startswith("REFREEZE_FIELDS_MISSING:BUNDLE_A") for block in report["release_blocks"])

    registry["bundles"] = [
        _bundle(
            str(repo["baseline"]),
            disposition={
                "state": "REFROZEN",
                "new_bundle_id": "BUNDLE_A_V2",
                "new_freeze_sha": str(repo["drift"]),
                "forward_clock_restart_at": "2026-09-14T14:00:00Z",
            },
        )
    ]
    good = build_reconciliation_report(
        repo=root, policy=_policy(), registry=registry, current_main_ref=str(repo["drift"])
    )
    assert good["release_ready"] is True


def test_revocation_invalidates_old_forward_clock(repo: dict[str, object]) -> None:
    registry = {
        "schema": "SPORTSEDGE_FREEZE_RECONCILIATION_REGISTRY_V1",
        "baseline_main_sha": repo["baseline"],
        "reconciled_through_sha": repo["drift"],
        "bundle_inventory_complete": True,
        "deltas": [_delta("DRIFT", str(repo["drift"]), 2)],
        "bundles": [
            _bundle(
                str(repo["baseline"]),
                disposition={
                    "state": "REVOKED",
                    "revoked_at": "2026-09-14T14:00:00Z",
                    "prior_forward_clock_invalidated": True,
                },
            )
        ],
    }
    report = build_reconciliation_report(
        repo=repo["root"],
        policy=_policy(),
        registry=registry,
        current_main_ref=str(repo["drift"]),
    )
    assert report["release_ready"] is True


def test_incomplete_bundle_inventory_is_a_hard_block(repo: dict[str, object]) -> None:
    registry = {
        "schema": "SPORTSEDGE_FREEZE_RECONCILIATION_REGISTRY_V1",
        "baseline_main_sha": repo["baseline"],
        "reconciled_through_sha": repo["irrelevant"],
        "bundle_inventory_complete": False,
        "deltas": [_delta("IRRELEVANT", str(repo["irrelevant"]), 1)],
        "bundles": [_bundle(str(repo["baseline"]))],
    }
    report = build_reconciliation_report(
        repo=repo["root"],
        policy=_policy(),
        registry=registry,
        current_main_ref=str(repo["irrelevant"]),
    )
    assert report["release_ready"] is False
    assert "ACTIVE_FREEZE_BUNDLE_INVENTORY_INCOMPLETE" in report["release_blocks"]


def test_governed_content_change_after_reconciliation_reblocks(repo: dict[str, object]) -> None:
    registry = {
        "schema": "SPORTSEDGE_FREEZE_RECONCILIATION_REGISTRY_V1",
        "baseline_main_sha": repo["baseline"],
        "reconciled_through_sha": repo["irrelevant"],
        "bundle_inventory_complete": True,
        "deltas": [_delta("IRRELEVANT", str(repo["irrelevant"]), 1)],
        "bundles": [_bundle(str(repo["baseline"]))],
    }
    report = build_reconciliation_report(
        repo=repo["root"],
        policy=_policy(),
        registry=registry,
        current_main_ref=str(repo["drift"]),
    )
    assert report["release_ready"] is False
    assert any(
        block.startswith("MAIN_GOVERNED_CONTENT_DIVERGED_FROM_RECONCILIATION")
        for block in report["release_blocks"]
    )
    boundary = report["boundary_identity"]
    assert boundary["ancestry_ok"] is True
    assert boundary["content_identity_ok"] is False


def test_repository_policy_is_unconditional_zero_authority_and_registers_late_deltas() -> None:
    policy = json.loads(Path("config/freeze_reconciliation_policy_v1.json").read_text())
    registry = json.loads(Path("config/freeze_reconciliation_registry_v1.json").read_text())
    assert policy["main_merge_hold"] == "UNCONDITIONAL"
    assert policy["status"] == "RESOLVED"
    assert policy["authorized_reconciliation_branch"] == "fix/freeze-reconciliation-inventory-20260914"
    assert policy["reconciliation_merge_method"] == "merge"
    assert policy["release_conditions"]["current_main_must_descend_from_reconciled_through_sha"] is True
    assert policy["release_conditions"]["current_governed_surface_digest_must_equal_registered_boundary_digest"] is True
    assert policy["release_conditions"]["sha_equality_is_not_a_terminal_condition"] is True
    assert not any(policy["authority"].values())
    ids = {row["delta_id"] for row in registry["deltas"]}
    assert {"PR_683", "PR_687", "PR_701", "PR_702", "PR_703"}.issubset(ids)
    assert registry["deltas"]
    current_main_ref = "HEAD" if os.environ.get("GITHUB_EVENT_NAME") == "pull_request" else "origin/main"
    current_main = _git(Path.cwd(), "rev-parse", current_main_ref)
    assert main_matches_reconciliation_boundary(
        Path.cwd(),
        policy=policy,
        registry=registry,
        reconciled_through_sha=registry["reconciled_through_sha"],
        current_main_ref=current_main,
    )
    assert registry["deltas"][-1]["merge_sha"] == registry["reconciled_through_sha"]
    assert registry["bundle_inventory_complete"] is False


def test_content_neutral_single_parent_successor_is_self_closing(repo: dict[str, object]) -> None:
    root = repo["root"]
    reconciled = str(repo["inventory_drift"])
    registry = {
        "schema": "SPORTSEDGE_FREEZE_RECONCILIATION_REGISTRY_V1",
        "baseline_main_sha": repo["baseline"],
        "reconciled_through_sha": reconciled,
        "bundle_inventory_complete": True,
        "deltas": [_delta("ANCHOR", reconciled, 1)],
        "bundles": [_bundle(str(repo["baseline"]))],
    }
    (root / "other.txt").write_text("squash-like neutral successor\n", encoding="utf-8")
    successor = _commit(root, "content-neutral single-parent successor")
    assert main_matches_reconciliation_boundary(
        root,
        policy=_policy(),
        registry=registry,
        reconciled_through_sha=reconciled,
        current_main_ref=successor,
    )
    before = governed_surface_digest(root, registry=registry, ref=reconciled)
    after = governed_surface_digest(root, registry=registry, ref=successor)
    assert before == after


def test_content_neutral_two_parent_merge_is_self_closing(repo: dict[str, object]) -> None:
    root = repo["root"]
    reconciled = str(repo["inventory_drift"])
    registry = {
        "schema": "SPORTSEDGE_FREEZE_RECONCILIATION_REGISTRY_V1",
        "baseline_main_sha": repo["baseline"],
        "reconciled_through_sha": reconciled,
        "bundle_inventory_complete": True,
        "deltas": [_delta("ANCHOR", reconciled, 1)],
        "bundles": [_bundle(str(repo["baseline"]))],
    }
    _git(root, "switch", "-c", "reconcile-terminal")
    (root / "reconciliation-note.txt").write_text("neutral\n", encoding="utf-8")
    branch_head = _commit(root, "content-neutral reconciliation change")
    _git(root, "switch", "main")
    _git(root, "merge", "--no-ff", branch_head, "-m", "merge reconciliation terminal")
    merge_sha = _git(root, "rev-parse", "HEAD")
    assert main_matches_reconciliation_boundary(
        root,
        policy=_policy(),
        registry=registry,
        reconciled_through_sha=reconciled,
        current_main_ref=merge_sha,
    )


def test_descendant_governed_change_fails_content_identity(repo: dict[str, object]) -> None:
    root = repo["root"]
    reconciled = str(repo["inventory_drift"])
    registry = {
        "schema": "SPORTSEDGE_FREEZE_RECONCILIATION_REGISTRY_V1",
        "baseline_main_sha": repo["baseline"],
        "reconciled_through_sha": reconciled,
        "bundle_inventory_complete": True,
        "deltas": [_delta("ANCHOR", reconciled, 1)],
        "bundles": [_bundle(str(repo["baseline"]))],
    }
    (root / "policy" / "freeze.txt").write_text("v3\n", encoding="utf-8")
    current = _commit(root, "governed descendant change")
    assert not main_matches_reconciliation_boundary(
        root,
        policy=_policy(),
        registry=registry,
        reconciled_through_sha=reconciled,
        current_main_ref=current,
    )


def test_non_descendant_matching_content_fails_ancestry(repo: dict[str, object]) -> None:
    root = repo["root"]
    reconciled = str(repo["irrelevant"])
    registry = {
        "schema": "SPORTSEDGE_FREEZE_RECONCILIATION_REGISTRY_V1",
        "baseline_main_sha": repo["baseline"],
        "reconciled_through_sha": reconciled,
        "bundle_inventory_complete": True,
        "deltas": [_delta("ANCHOR", reconciled, 1)],
        "bundles": [_bundle(str(repo["baseline"]))],
    }
    _git(root, "switch", "-c", "divergent", str(repo["baseline"]))
    (root / "other.txt").write_text("different ungoverned branch\n", encoding="utf-8")
    divergent = _commit(root, "divergent content-neutral branch")
    assert governed_surface_digest(root, registry=registry, ref=reconciled) == governed_surface_digest(
        root, registry=registry, ref=divergent
    )
    assert not main_matches_reconciliation_boundary(
        root,
        policy=_policy(),
        registry=registry,
        reconciled_through_sha=reconciled,
        current_main_ref=divergent,
    )


def test_722_merge_is_governed_content_neutral() -> None:
    root = Path.cwd()
    registry = json.loads(Path("config/freeze_reconciliation_registry_v1.json").read_text())
    registered = "a6e5a155edc9bc59676816091473a8540d694e0c"
    merged = "bd47021bd2d0fbb748e64795f0b37108a70b4389"
    registered_digest = governed_surface_digest(root, registry=registry, ref=registered)
    merged_digest = governed_surface_digest(root, registry=registry, ref=merged)
    assert registered_digest == merged_digest, (
        "#722 merge changed governed content: "
        f"registered={registered_digest} merged={merged_digest}"
    )


def test_invalid_non_unconditional_policy_fails_closed(repo: dict[str, object]) -> None:
    policy = _policy()
    policy["main_merge_hold"] = "GOVERNANCE_ONLY"
    registry = {
        "schema": "SPORTSEDGE_FREEZE_RECONCILIATION_REGISTRY_V1",
        "baseline_main_sha": repo["baseline"],
        "reconciled_through_sha": repo["irrelevant"],
        "bundle_inventory_complete": True,
        "deltas": [_delta("IRRELEVANT", str(repo["irrelevant"]), 1)],
        "bundles": [_bundle(str(repo["baseline"]))],
    }
    with pytest.raises(FreezeReconciliationError, match="MUST_BE_UNCONDITIONAL"):
        build_reconciliation_report(
            repo=repo["root"],
            policy=policy,
            registry=registry,
            current_main_ref=str(repo["irrelevant"]),
        )


def test_ready_matrix_does_not_release_an_active_hold(repo: dict[str, object]) -> None:
    registry = {
        "schema": "SPORTSEDGE_FREEZE_RECONCILIATION_REGISTRY_V1",
        "baseline_main_sha": repo["baseline"],
        "reconciled_through_sha": repo["irrelevant"],
        "bundle_inventory_complete": True,
        "deltas": [_delta("IRRELEVANT", str(repo["irrelevant"]), 1)],
        "bundles": [_bundle(str(repo["baseline"]))],
    }
    policy = _policy()
    active = build_reconciliation_report(
        repo=repo["root"], policy=policy, registry=registry,
        current_main_ref=str(repo["irrelevant"]),
    )
    assert active["release_ready"] is True
    assert active["release_authorized"] is False
    policy["status"] = "RESOLVED"
    resolved = build_reconciliation_report(
        repo=repo["root"], policy=policy, registry=registry,
        current_main_ref=str(repo["irrelevant"]),
    )
    assert resolved["release_authorized"] is True
    assert active["report_sha256"] != resolved["report_sha256"]
    advanced = build_reconciliation_report(
        repo=repo["root"], policy=policy, registry=registry,
        current_main_ref=str(repo["drift"]),
    )
    assert advanced["release_ready"] is False
    assert advanced["release_authorized"] is False
