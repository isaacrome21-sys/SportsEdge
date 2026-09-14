#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sportsedge.governance.freeze_reconciliation import (  # noqa: E402
    build_reconciliation_report,
    load_json,
)
from sportsedge.governance.reconciliation_content_boundary import (  # noqa: E402
    evaluate_content_boundary,
)
from scripts.reconcile_freeze_deltas import assert_refreeze_machine_verified  # noqa: E402


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile registered deltas and enforce a non-self-aging content-identity main boundary."
    )
    parser.add_argument("--policy", default="config/freeze_reconciliation_policy_v1.json")
    parser.add_argument("--registry", default="config/freeze_reconciliation_registry_v1.json")
    parser.add_argument("--boundary", default="config/reconciliation_content_boundary_v1.json")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--current-main-ref", default="main")
    parser.add_argument("--candidate-ref")
    parser.add_argument("--output")
    parser.add_argument("--require-release-ready", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    policy = load_json(args.policy)
    registry = load_json(args.registry)
    boundary = load_json(args.boundary)
    assert_refreeze_machine_verified(registry)

    # Matrix reconciliation is a historical replay over explicitly registered
    # deltas. Its old exact-head argument is pinned to the registered historical
    # point so it cannot re-introduce the impossible self-hash predicate. Current
    # main admissibility is decided below by content identity instead.
    historical_ref = str(registry["reconciled_through_sha"])
    report = build_reconciliation_report(
        repo=repo,
        policy=policy,
        registry=registry,
        current_main_ref=historical_ref,
    )

    boundary_eval = evaluate_content_boundary(
        repo=repo,
        registry=registry,
        boundary=boundary,
        current_main_ref=args.current_main_ref,
        candidate_ref=args.candidate_ref,
    )

    blocks = [
        block
        for block in report.get("release_blocks") or []
        if not str(block).startswith("MAIN_ADVANCED_BEYOND_RECONCILIATION:")
    ]
    blocks.extend(boundary_eval.release_blocks)
    blocks = sorted(set(str(block) for block in blocks))
    release_ready = not blocks
    release_authorized = release_ready and policy["status"] == "RESOLVED"

    report["schema"] = "SPORTSEDGE_FREEZE_RECONCILIATION_REPORT_V2_CONTENT_BOUNDARY"
    report["current_main_sha"] = boundary_eval.current_main_sha
    report["legacy_reconciled_through_sha"] = report.pop("reconciled_through_sha")
    report["content_boundary"] = boundary_eval.as_dict()
    report["release_blocks"] = blocks
    report["release_ready"] = release_ready
    report["release_authorized"] = release_authorized
    report["report_sha256"] = _canonical_sha256(
        {
            "schema": report["schema"],
            "current_main_sha": report["current_main_sha"],
            "baseline_main_sha": report["baseline_main_sha"],
            "legacy_reconciled_through_sha": report["legacy_reconciled_through_sha"],
            "rows": report["rows"],
            "content_boundary": report["content_boundary"],
            "blocks": blocks,
            "policy_status": policy["status"],
            "release_authorized": release_authorized,
        }
    )

    rendered = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if args.require_release_ready and not release_ready:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
