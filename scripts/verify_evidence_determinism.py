#!/usr/bin/env python3
"""Verify byte-exact replay of promotion evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.core.validation.evidence_determinism import compare_evidence_directories

_EXIT_CODE = {"PASS": 0, "FAIL": 2, "BLOCKED": 3}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two evidence directories at identical code/source identity. "
            "PASS requires byte-identical requested artifacts; semantic JSON "
            "comparison is diagnostic-only after a byte mismatch. FAIL is a "
            "same-identity byte mismatch; BLOCKED means like-for-like replay "
            "was not provable."
        )
    )
    parser.add_argument("--sport", choices=("mlb", "cfb", "nfl"), required=True)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--artifact", action="append", required=True, help="Relative JSON artifact path; repeatable")
    parser.add_argument("--identity-artifact", help="Artifact carrying code_git_sha and the configured source identity SHA")
    parser.add_argument("--expected-git-sha", required=True)
    parser.add_argument(
        "--determinism-class",
        required=True,
        help="Explicit certification class, e.g. SAME_ENV_SAME_SHA",
    )
    parser.add_argument(
        "--replay-scope",
        required=True,
        help="Exact pipeline boundary certified by this replay",
    )
    parser.add_argument(
        "--clock-perturbation",
        help="Declared clock/timezone perturbation applied to replay B, if any",
    )
    parser.add_argument(
        "--source-identity-field",
        default="source_manifest_sha256",
        help=(
            "SHA-256 field in the identity artifact that binds frozen inputs. "
            "Use training_bundle_sha256 for CFB bundle-to-artifact replay."
        ),
    )
    parser.add_argument("--baseline-label", default="ATTEMPT_001")
    parser.add_argument("--candidate-label", default="REPLAY")
    parser.add_argument("--max-differences", type=int, default=100)
    parser.add_argument(
        "--allow-missing-source-manifest",
        action="store_true",
        help=(
            "Diagnostic-only escape hatch. Promotion workflows must not use this; "
            "the default requires the configured source identity SHA on both identity artifacts."
        ),
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    identity = args.identity_artifact or args.artifact[0]
    report = compare_evidence_directories(
        sport=args.sport,
        baseline_dir=args.baseline_dir,
        candidate_dir=args.candidate_dir,
        artifacts=args.artifact,
        identity_artifact=identity,
        expected_git_sha=args.expected_git_sha,
        determinism_class=args.determinism_class,
        replay_scope=args.replay_scope,
        clock_perturbation=args.clock_perturbation,
        baseline_label=args.baseline_label,
        candidate_label=args.candidate_label,
        source_identity_field=args.source_identity_field,
        require_source_manifest=not args.allow_missing_source_manifest,
        max_differences=args.max_differences,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return _EXIT_CODE[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
