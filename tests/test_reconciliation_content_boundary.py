from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sportsedge.governance.reconciliation_content_boundary import (
    BOUNDARY_SCHEMA,
    evaluate_content_boundary,
    governed_surface_registry_digest,
)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
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
    anchor = _commit(root, "anchor")
    registry = {
        "schema": "SPORTSEDGE_FREEZE_RECONCILIATION_REGISTRY_V1",
        "bundle_inventory_complete": True,
        "inventory_block_reason": None,
        "bundles": [
            {
                "bundle_id": "BUNDLE_A",
                "freeze_sha": anchor,
                "coverage_prefixes": ["policy/"],
                "disposition": None,
            }
        ],
        "baseline_main_sha": anchor,
        "reconciled_through_sha": anchor,
        "deltas": [{"delta_id": "ANCHOR", "pr": 0, "merge_sha": anchor}],
    }
    digest = governed_surface_registry_digest(repo=root, registry=registry, ref=anchor)
    boundary = {
        "schema": BOUNDARY_SCHEMA,
        "anchor_main_sha": anchor,
        "predecessor_governed_surface_digest_sha256": digest,
        "registered_governed_surface_digest_sha256": digest,
        "merge_strategy": {
            "preferred_method": "merge",
            "digest_primary": True,
            "parentage_corroboration": "OPTIONAL_ONE_STEP_TWO_PARENT_MERGE",
            "squash_behavior": "DIGEST_PRIMARY_PARENTAGE_UNAVAILABLE",
        },
        "authority": {
            "model": False,
            "truth_gate": False,
            "promotion": False,
            "staking": False,
            "official": False,
            "validation_attempt": False,
            "readout": False,
        },
    }
    return {"root": root, "anchor": anchor, "registry": registry, "boundary": boundary}


def test_descendant_with_unchanged_governed_surface_remains_admissible(repo: dict[str, object]) -> None:
    root = repo["root"]
    (root / "other.txt").write_text("non-governed movement\n", encoding="utf-8")
    descendant = _commit(root, "non-governed movement")
    result = evaluate_content_boundary(
        repo=root,
        registry=repo["registry"],
        boundary=repo["boundary"],
        current_main_ref=descendant,
    )
    assert result.admissible is True
    assert result.current_main_sha != result.anchor_main_sha
    assert result.current_governed_surface_digest_sha256 == result.registered_governed_surface_digest_sha256


def test_governed_surface_change_reblocks_without_boundary_update(repo: dict[str, object]) -> None:
    root = repo["root"]
    (root / "policy" / "freeze.txt").write_text("v2\n", encoding="utf-8")
    changed = _commit(root, "governed change")
    result = evaluate_content_boundary(
        repo=root,
        registry=repo["registry"],
        boundary=repo["boundary"],
        current_main_ref=changed,
    )
    assert result.admissible is False
    assert any(
        block.startswith("CURRENT_MAIN_GOVERNED_SURFACE_DIGEST_MISMATCH:")
        for block in result.release_blocks
    )


def test_merge_commit_is_self_closing_without_storing_its_own_sha(repo: dict[str, object]) -> None:
    root = repo["root"]
    anchor = repo["anchor"]
    _git(root, "switch", "-c", "reconciliation")
    (root / "other.txt").write_text("reconciliation control-plane note\n", encoding="utf-8")
    branch_head = _commit(root, "reconciliation candidate")
    _git(root, "switch", "main")
    _git(root, "merge", "--no-ff", branch_head, "-m", "merge reconciliation")
    merged = _git(root, "rev-parse", "HEAD")

    result = evaluate_content_boundary(
        repo=root,
        registry=repo["registry"],
        boundary=repo["boundary"],
        current_main_ref=merged,
    )
    assert result.admissible is True
    assert merged != anchor
    assert result.one_step_merge_parentage_corroborated is True


def test_squash_successor_uses_digest_when_parentage_is_unavailable(repo: dict[str, object]) -> None:
    root = repo["root"]
    _git(root, "switch", "-c", "reconciliation-squash")
    (root / "other.txt").write_text("squash-safe control plane\n", encoding="utf-8")
    _commit(root, "candidate")
    _git(root, "switch", "main")
    _git(root, "merge", "--squash", "reconciliation-squash")
    squashed = _commit(root, "squash reconciliation")

    result = evaluate_content_boundary(
        repo=root,
        registry=repo["registry"],
        boundary=repo["boundary"],
        current_main_ref=squashed,
    )
    assert result.admissible is True
    assert result.one_step_merge_parentage_corroborated is False


def test_transition_pr_can_register_candidate_digest_before_merge(repo: dict[str, object]) -> None:
    root = repo["root"]
    anchor = repo["anchor"]
    predecessor = repo["boundary"]["registered_governed_surface_digest_sha256"]

    _git(root, "switch", "-c", "reconcile-governed-change")
    (root / "policy" / "freeze.txt").write_text("v2\n", encoding="utf-8")
    candidate = _commit(root, "candidate governed transition")
    registered = governed_surface_registry_digest(
        repo=root, registry=repo["registry"], ref=candidate
    )
    boundary = dict(repo["boundary"])
    boundary["anchor_main_sha"] = anchor
    boundary["predecessor_governed_surface_digest_sha256"] = predecessor
    boundary["registered_governed_surface_digest_sha256"] = registered

    _git(root, "switch", "main")
    premerge = evaluate_content_boundary(
        repo=root,
        registry=repo["registry"],
        boundary=boundary,
        current_main_ref=anchor,
        candidate_ref=candidate,
    )
    assert premerge.admissible is True
    assert premerge.transition_mode == "PREMERGE_BOUNDARY_TRANSITION"

    _git(root, "merge", "--no-ff", candidate, "-m", "merge governed reconciliation")
    merged = _git(root, "rev-parse", "HEAD")
    postmerge = evaluate_content_boundary(
        repo=root,
        registry=repo["registry"],
        boundary=boundary,
        current_main_ref=merged,
    )
    assert postmerge.admissible is True
    assert postmerge.current_governed_surface_digest_sha256 == registered
