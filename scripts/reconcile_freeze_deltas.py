#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


def assert_refreeze_machine_verified(registry: dict[str, object]) -> None:
    refrozen: list[str] = []
    for bundle in registry.get("bundles") or []:
        if not isinstance(bundle, dict):
            continue
        disposition = bundle.get("disposition")
        if isinstance(disposition, dict) and disposition.get("state") == "REFROZEN":
            refrozen.append(str(bundle.get("bundle_id") or "UNKNOWN_BUNDLE"))
    if refrozen:
        raise SystemExit(
            "REFROZEN_SEMANTICS_NOT_MACHINE_VERIFIED:"
            + ",".join(sorted(refrozen))
            + ":ONLY_REVOKED_ALLOWED_UNTIL_PRIOR_BUNDLE_HASH_TIMESTAMP_AND_ROW_ADMISSIBILITY_ARE_VERIFIED"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile every registered post-freeze delta against every active freeze bundle."
    )
    parser.add_argument(
        "--policy", default="config/freeze_reconciliation_policy_v1.json"
    )
    parser.add_argument(
        "--registry", default="config/freeze_reconciliation_registry_v1.json"
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--current-main-ref", default="main")
    parser.add_argument("--output")
    parser.add_argument("--require-release-ready", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    policy = load_json(args.policy)
    registry = load_json(args.registry)
    assert_refreeze_machine_verified(registry)
    report = build_reconciliation_report(
        repo=repo,
        policy=policy,
        registry=registry,
        current_main_ref=args.current_main_ref,
    )
    rendered = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if args.require_release_ready and not report["release_ready"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
