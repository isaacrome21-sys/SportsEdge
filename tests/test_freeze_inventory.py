from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from sportsedge.governance.freeze_inventory import FreezeInventoryError, audit_inventory


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "config").mkdir()
    (repo / "tests").mkdir()
    return repo


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _policy(exemptions=None):
    return {
        "schema": "SPORTSEDGE_FREEZE_INVENTORY_POLICY_V1",
        "candidate_roots": ["config/"],
        "candidate_path_tokens": ["freeze", "prereg", "evidence", "truth_gate"],
        "content_scan_suffixes": [".json"],
        "content_markers": ["FROZEN_", "promotion_authority"],
        "exact_exemptions": exemptions or {},
        "authority": {"model_p": False, "promotion": False},
    }


def _registry(*, complete: bool, prefixes=None):
    return {
        "bundle_inventory_complete": complete,
        "bundles": [
            {
                "bundle_id": "BUNDLE_V1",
                "freeze_sha": "unused",
                "coverage_prefixes": prefixes or ["config/covered_"],
            }
        ],
    }


def test_new_freeze_file_is_unmapped_and_blocks(tmp_path: Path):
    repo = _repo(tmp_path)
    (repo / "config" / "surprise_freeze.json").write_text('{"status":"FROZEN_READY"}\n')
    _commit(repo, "add surprise")
    report = audit_inventory(repo=repo, ref="HEAD", policy=_policy(), registry=_registry(complete=False))
    assert report["computed_complete"] is False
    assert report["unmapped_paths"] == ["config/surprise_freeze.json"]


def test_innocuous_name_with_governance_marker_is_still_candidate(tmp_path: Path):
    repo = _repo(tmp_path)
    (repo / "config" / "plain.json").write_text('{"promotion_authority":false}\n')
    _commit(repo, "add semantic surface")
    report = audit_inventory(repo=repo, ref="HEAD", policy=_policy(), registry=_registry(complete=False))
    assert "config/plain.json" in report["unmapped_paths"]


def test_bundle_mapping_computes_complete(tmp_path: Path):
    repo = _repo(tmp_path)
    (repo / "config" / "covered_freeze.json").write_text('{"status":"FROZEN_READY"}\n')
    _commit(repo, "add mapped")
    report = audit_inventory(repo=repo, ref="HEAD", policy=_policy(), registry=_registry(complete=True))
    assert report["computed_complete"] is True
    assert report["claim_matches_computation"] is True
    assert report["release_blocks"] == []


def test_exact_exemption_is_allowed_but_wildcard_is_forbidden(tmp_path: Path):
    repo = _repo(tmp_path)
    (repo / "config" / "control_freeze.json").write_text('{"status":"FROZEN_READY"}\n')
    _commit(repo, "add control")
    report = audit_inventory(
        repo=repo,
        ref="HEAD",
        policy=_policy({"config/control_freeze.json": "CONTROL_PLANE"}),
        registry=_registry(complete=True),
    )
    assert report["computed_complete"] is True
    with pytest.raises(FreezeInventoryError, match="WILDCARD_EXEMPTION_FORBIDDEN"):
        audit_inventory(
            repo=repo,
            ref="HEAD",
            policy=_policy({"config/*": "TOO_BROAD"}),
            registry=_registry(complete=False),
        )


def test_stale_exemption_blocks_completion(tmp_path: Path):
    repo = _repo(tmp_path)
    (repo / "config" / "covered_freeze.json").write_text('{"status":"FROZEN_READY"}\n')
    _commit(repo, "base")
    report = audit_inventory(
        repo=repo,
        ref="HEAD",
        policy=_policy({"config/does_not_exist.json": "STALE"}),
        registry=_registry(complete=False),
    )
    assert report["computed_complete"] is False
    assert report["stale_exemptions"] == ["config/does_not_exist.json"]
