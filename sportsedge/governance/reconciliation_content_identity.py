from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping


class ReconciliationContentIdentityError(RuntimeError):
    pass


def _canonical_sha256(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return sha256(raw).hexdigest()


def _git(repo: Path, *args: str, text: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=text, check=False)
    if proc.returncode != 0:
        stderr = proc.stderr.strip() if text else proc.stderr.decode("utf-8", "replace")
        raise ReconciliationContentIdentityError(
            f"GIT_COMMAND_FAILED:{' '.join(args)}:{proc.returncode}:{stderr}"
        )
    return proc


def resolve_sha(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", ref).stdout.strip()


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    raise ReconciliationContentIdentityError(
        f"GIT_ANCESTRY_FAILED:{ancestor}:{descendant}:{proc.returncode}:{proc.stderr.strip()}"
    )


def _covered(path: str, bundle: Mapping[str, Any]) -> bool:
    exact = {str(value) for value in bundle.get("coverage_paths") or ()}
    prefixes = tuple(str(value) for value in bundle.get("coverage_prefixes") or ())
    return path in exact or any(path.startswith(prefix) for prefix in prefixes)


def governed_surface_digest(
    repo: Path,
    *,
    registry: Mapping[str, Any],
    ref: str,
) -> str:
    """Hash the exact governed bytes/inventory selected by the effective registry.

    The commit SHA is deliberately excluded. Identity is the sorted set of active
    bundle selectors plus the selected path/blob hashes at ``ref``. This makes a
    governance-neutral descendant content-identical while any covered byte or
    covered inventory change alters the digest.
    """
    resolved = resolve_sha(repo, ref)
    tree = tuple(
        line.strip()
        for line in _git(repo, "ls-tree", "-r", "--name-only", resolved).stdout.splitlines()
        if line.strip()
    )
    bundle_rows: list[dict[str, object]] = []
    bundles = registry.get("bundles") or ()
    if not isinstance(bundles, list) or not bundles:
        raise ReconciliationContentIdentityError("GOVERNED_SURFACE_BUNDLES_EMPTY")
    for bundle in sorted(bundles, key=lambda item: str(item.get("bundle_id") or "")):
        if not isinstance(bundle, Mapping) or not bundle.get("bundle_id"):
            raise ReconciliationContentIdentityError("GOVERNED_SURFACE_BUNDLE_INVALID")
        files: list[tuple[str, str]] = []
        for path in tree:
            if not _covered(path, bundle):
                continue
            blob = _git(repo, "show", f"{resolved}:{path}", text=False).stdout
            files.append((path, sha256(bytes(blob)).hexdigest()))
        files.sort()
        bundle_rows.append(
            {
                "bundle_id": str(bundle["bundle_id"]),
                "coverage_paths": sorted(str(v) for v in (bundle.get("coverage_paths") or ())),
                "coverage_prefixes": sorted(str(v) for v in (bundle.get("coverage_prefixes") or ())),
                "files": files,
            }
        )
    return _canonical_sha256({"schema": "SPORTSEDGE_GOVERNED_SURFACE_IDENTITY_V1", "bundles": bundle_rows})


def boundary_matches(
    repo: Path,
    *,
    registry: Mapping[str, Any],
    registered_ref: str,
    current_ref: str,
) -> tuple[bool, dict[str, object]]:
    registered_sha = resolve_sha(repo, registered_ref)
    current_sha = resolve_sha(repo, current_ref)
    ancestry_ok = is_ancestor(repo, registered_sha, current_sha)
    registered_digest = governed_surface_digest(repo, registry=registry, ref=registered_sha)
    current_digest = governed_surface_digest(repo, registry=registry, ref=current_sha)
    digest_ok = registered_digest == current_digest
    return ancestry_ok and digest_ok, {
        "registered_sha": registered_sha,
        "current_sha": current_sha,
        "ancestry_ok": ancestry_ok,
        "registered_governed_surface_sha256": registered_digest,
        "current_governed_surface_sha256": current_digest,
        "content_identity_ok": digest_ok,
    }
