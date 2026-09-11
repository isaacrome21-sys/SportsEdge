#!/usr/bin/env python3
"""Build a deterministic NFL football-prop model artifact from frozen PBP files.

This file is intentionally touched on current main so the hosted exact-SHA freeze
workflow re-runs against the current production loader before any checked-in
freeze registry is allowed to change. The builder itself has no promotion authority.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.football_prop_run_machine import canonical_hash
from sportsedge.sports.nfl.prop_artifact_training import fit_nfl_prop_artifact


def _write(path: Path, payload: dict) -> None:
    # Validate with the same JSON domain used by the production hash function.
    # In particular, never persist NaN/Infinity as apparently valid JSON.
    canonical_hash(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbp", type=Path, nargs="+", required=True)
    ap.add_argument("--git-sha", required=True)
    ap.add_argument("--artifact-version", required=True)
    ap.add_argument("--seasons", nargs="+", type=int, default=[2022, 2023, 2024, 2025])
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument(
        "--artifact-path", type=Path,
        help="Declared runtime artifact path; defaults to --output. Use the same runtime path for independent replay staging directories.",
    )
    ap.add_argument("--diagnostics-output", type=Path, required=True)
    ap.add_argument("--freeze-output", type=Path, required=True)
    args = ap.parse_args()

    artifact, diagnostics = fit_nfl_prop_artifact(
        args.pbp,
        code_git_sha=args.git_sha,
        artifact_version=args.artifact_version,
        seasons=args.seasons,
    )
    artifact_sha = canonical_hash(artifact)
    freeze = {
        "schema_version": 1,
        "sport": "NFL",
        "status": "FROZEN",
        "hash_algorithm": "CANONICAL_JSON_SHA256_V1",
        "artifact_path": str(args.artifact_path if args.artifact_path is not None else args.output),
        "artifact_sha256": artifact_sha,
        "code_git_sha": str(args.git_sha).lower(),
        "source_manifest_sha256": artifact["source_manifest_sha256"],
        "artifact_version": artifact["artifact_version"],
        "promotion_authority": False,
    }
    diagnostics["artifact_sha256"] = artifact_sha
    _write(args.output, artifact)
    _write(args.diagnostics_output, diagnostics)
    _write(args.freeze_output, freeze)
    print(json.dumps({
        "status": diagnostics["status"],
        "artifact_sha256": artifact_sha,
        "source_manifest_sha256": artifact["source_manifest_sha256"],
        "team_count": diagnostics["team_count"],
        "output": str(args.output),
        "freeze_output": str(args.freeze_output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
