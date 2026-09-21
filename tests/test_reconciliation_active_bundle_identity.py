from __future__ import annotations

import subprocess
from pathlib import Path

from sportsedge.governance.reconciliation_content_identity import governed_surface_digest


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=True
    )
    return proc.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "SportsEdge Test")
    (repo / "active.txt").write_text("active-v1\n", encoding="utf-8")
    (repo / "revoked.txt").write_text("revoked-v1\n", encoding="utf-8")
    return repo, _commit(repo, "baseline")


def _registry() -> dict[str, object]:
    return {
        "bundles": [
            {
                "bundle_id": "ACTIVE",
                "coverage_paths": ["active.txt"],
                "disposition": None,
            },
            {
                "bundle_id": "REVOKED",
                "coverage_paths": ["revoked.txt"],
                "disposition": {
                    "state": "REVOKED",
                    "revoked_at": "2026-09-21T16:07:00Z",
                    "prior_forward_clock_invalidated": True,
                },
            },
        ]
    }


def test_revoked_bundle_bytes_do_not_reopen_active_content_identity(tmp_path: Path) -> None:
    repo, baseline = _repo(tmp_path)
    registry = _registry()
    before = governed_surface_digest(repo, registry=registry, ref=baseline)
    (repo / "revoked.txt").write_text("revoked-v2\n", encoding="utf-8")
    after_sha = _commit(repo, "change revoked surface")
    after = governed_surface_digest(repo, registry=registry, ref=after_sha)
    assert after == before


def test_active_bundle_bytes_still_change_content_identity(tmp_path: Path) -> None:
    repo, baseline = _repo(tmp_path)
    registry = _registry()
    before = governed_surface_digest(repo, registry=registry, ref=baseline)
    (repo / "active.txt").write_text("active-v2\n", encoding="utf-8")
    after_sha = _commit(repo, "change active surface")
    after = governed_surface_digest(repo, registry=registry, ref=after_sha)
    assert after != before
