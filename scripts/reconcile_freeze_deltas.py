#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.governance.freeze_reconciliation import (
    build_reconciliation_report,
    load_json,
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
    report = build_reconciliation_report(
        repo=repo,
        policy=load_json(args.policy),
        registry=load_json(args.registry),
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
