#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sportsedge.governance.freeze_inventory import audit_inventory, load_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit every plausible freeze/governance surface against the reconciliation bundle registry.")
    parser.add_argument("--policy", default="config/freeze_inventory_policy_v1.json")
    parser.add_argument("--registry", default="config/freeze_reconciliation_registry_v1.json")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--output")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()

    report = audit_inventory(
        repo=Path(args.repo).resolve(),
        ref=args.ref,
        policy=load_json(args.policy),
        registry=load_json(args.registry),
    )
    rendered = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if args.require_complete and report["release_blocks"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
