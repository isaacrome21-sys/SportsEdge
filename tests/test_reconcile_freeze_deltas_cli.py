from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from scripts.reconcile_freeze_deltas import assert_refreeze_machine_verified
from sportsedge.governance.freeze_reconciliation import bundle_snapshot


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
def refreeze_case(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "SportsEdge Test")
    (root / "policy").mkdir()
    (root / "policy" / "freeze.txt").write_text("v1\n", encoding="utf-8")
    old_sha = _commit(root, "old freeze")
    (root / "policy" / "freeze.txt").write_text("v2\n", encoding="utf-8")
    new_sha = _commit(root, "covered drift and refreeze")
    bundle = {
        "bundle_id": "BUNDLE_A",
        "freeze_sha": old_sha,
        "coverage_prefixes": ["policy/"],
    }
    prior_hash = bundle_snapshot(root, bundle, old_sha).aggregate_sha256
    new_hash = bundle_snapshot(root, bundle, new_sha).aggregate_sha256
    bundle["disposition"] = {
        "state": "REFROZEN",
        "new_bundle_id": "BUNDLE_A_V2",
        "new_freeze_sha": new_sha,
        "forward_clock_restart_at": "2026-09-14T14:00:00Z",
        "prior_bundle_hash": prior_hash,
        "new_bundle_hash": new_hash,
        "prior_semantics_invalid_after": "2026-09-14T14:00:00Z",
        "prior_evidence_invalidation_rule": "HASH_AND_TIME",
    }
    registry = {"reconciled_through_sha": new_sha, "bundles": [bundle]}
    report = {
        "rows": [
            {
                "bundle_id": "BUNDLE_A",
                "outcome": "DRIFT_CONFIRMED",
                "merge_sha": new_sha,
                "delta_id": "DRIFT",
            }
        ]
    }
    return {"root": root, "registry": registry, "report": report}


def test_refrozen_disposition_passes_only_with_replayed_hash_time_and_rows(
    refreeze_case: dict[str, object],
) -> None:
    assert_refreeze_machine_verified(
        repo=refreeze_case["root"],
        registry=refreeze_case["registry"],
        report=refreeze_case["report"],
    )


def test_refrozen_disposition_rejects_hash_mismatch(
    refreeze_case: dict[str, object],
) -> None:
    registry = refreeze_case["registry"]
    registry["bundles"][0]["disposition"]["new_bundle_hash"] = "0" * 64
    with pytest.raises(SystemExit, match="REFROZEN_NEW_BUNDLE_HASH_MISMATCH:BUNDLE_A"):
        assert_refreeze_machine_verified(
            repo=refreeze_case["root"],
            registry=registry,
            report=refreeze_case["report"],
        )


def test_refrozen_disposition_rejects_unbound_semantics(
    refreeze_case: dict[str, object],
) -> None:
    registry = refreeze_case["registry"]
    del registry["bundles"][0]["disposition"]["prior_bundle_hash"]
    with pytest.raises(SystemExit, match="REFROZEN_MACHINE_FIELDS_MISSING:BUNDLE_A"):
        assert_refreeze_machine_verified(
            repo=refreeze_case["root"],
            registry=registry,
            report=refreeze_case["report"],
        )


def test_refrozen_disposition_rejects_drift_after_new_freeze(
    refreeze_case: dict[str, object],
) -> None:
    root = refreeze_case["root"]
    (root / "policy" / "freeze.txt").write_text("v3\n", encoding="utf-8")
    later_sha = _commit(root, "later covered drift")
    refreeze_case["registry"]["reconciled_through_sha"] = later_sha
    refreeze_case["report"]["rows"].append(
        {
            "bundle_id": "BUNDLE_A",
            "outcome": "DRIFT_CONFIRMED",
            "merge_sha": later_sha,
            "delta_id": "LATE_DRIFT",
        }
    )
    with pytest.raises(SystemExit, match="REFROZEN_DRIFT_NOT_INCLUDED:BUNDLE_A:LATE_DRIFT"):
        assert_refreeze_machine_verified(
            repo=root,
            registry=refreeze_case["registry"],
            report=refreeze_case["report"],
        )


def test_revoked_disposition_remains_allowed(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "SportsEdge Test")
    (root / "README").write_text("x\n", encoding="utf-8")
    sha = _commit(root, "base")
    registry = {
        "reconciled_through_sha": sha,
        "bundles": [
            {
                "bundle_id": "BUNDLE_A",
                "disposition": {
                    "state": "REVOKED",
                    "revoked_at": "2026-09-14T14:00:00Z",
                    "prior_forward_clock_invalidated": True,
                },
            }
        ],
    }
    assert_refreeze_machine_verified(repo=root, registry=registry, report={"rows": []})
