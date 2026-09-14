#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sportsedge.governance.reconciliation_content_boundary import (  # noqa: E402
    governed_surface_registry_digest,
)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"GIT_COMMAND_FAILED:{' '.join(args)}:{proc.returncode}:{proc.stderr.strip()}"
        )
    return proc.stdout


def _json_at_ref(repo: Path, ref: str, path: str) -> dict[str, Any]:
    payload = json.loads(_git(repo, "show", f"{ref}:{path}"))
    if not isinstance(payload, dict):
        raise SystemExit(f"JSON_OBJECT_REQUIRED:{ref}:{path}")
    return payload


def _merge_view_function():
    script = REPO_ROOT / "scripts" / "build_reconciliation_registry_view.py"
    spec = importlib.util.spec_from_file_location("sportsedge_registry_view", script)
    if spec is None or spec.loader is None:
        raise SystemExit("REGISTRY_VIEW_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.merge_view


def effective_registry_at_ref(repo: Path, ref: str) -> dict[str, Any]:
    policy = _json_at_ref(repo, ref, "config/freeze_inventory_policy_v1.json")
    registry = _json_at_ref(repo, ref, "config/freeze_reconciliation_registry_v1.json")
    extension = _json_at_ref(repo, ref, "config/reconciliation_coverage_v1.json")
    _effective_policy, effective_registry, _attestation = _merge_view_function()(
        policy, registry, extension
    )
    return effective_registry


def digest_at_ref(repo: Path, ref: str) -> str:
    registry = effective_registry_at_ref(repo, ref)
    return governed_surface_registry_digest(repo=repo, registry=registry, ref=ref)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute the content-identity digest of the effective governed freeze registry at one or two refs."
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--ref", required=True)
    parser.add_argument("--compare-ref")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    primary_sha = _git(repo, "rev-parse", args.ref).strip()
    primary_digest = digest_at_ref(repo, primary_sha)
    result: dict[str, Any] = {
        "schema": "SPORTSEDGE_RECONCILIATION_CONTENT_DIGEST_DIAGNOSTIC_V1",
        "ref": args.ref,
        "resolved_sha": primary_sha,
        "governed_surface_registry_digest_sha256": primary_digest,
    }
    if args.compare_ref:
        compare_sha = _git(repo, "rev-parse", args.compare_ref).strip()
        compare_digest = digest_at_ref(repo, compare_sha)
        result["compare_ref"] = args.compare_ref
        result["compare_resolved_sha"] = compare_sha
        result["compare_governed_surface_registry_digest_sha256"] = compare_digest
        result["digests_match"] = primary_digest == compare_digest
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
