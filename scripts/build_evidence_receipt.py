#!/usr/bin/env python3
"""Build or verify a canonical SportsEdge evidence receipt.

This tool is intentionally external to frozen capture jobs.  In particular, it
can bind an NFL capture directory without changing the hash-locked capture
script/workflow that produced it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from sportsedge.core.validation.evidence_receipt import (
    build_receipt,
    verify_receipt,
    write_receipt,
)


def _files(root: Path, values: list[str]) -> list[Path]:
    out: list[Path] = []
    for value in values:
        path = root / value
        if path.is_dir():
            out.extend(sorted(p for p in path.rglob("*") if p.is_file()))
        else:
            out.append(path)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--lane")
    parser.add_argument("--input", action="append", default=[])
    parser.add_argument("--output", action="append", default=[])
    parser.add_argument("--policy")
    parser.add_argument("--metadata-json", default="{}")
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root)
    receipt_path = root / args.receipt

    if args.verify:
        if not receipt_path.is_file():
            print(json.dumps({"status": "FAIL", "errors": ["RECEIPT_MISSING"]}, sort_keys=True))
            return 2
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        errors = verify_receipt(receipt, root=root)
        print(json.dumps({"status": "PASS" if not errors else "FAIL", "errors": errors}, sort_keys=True))
        return 0 if not errors else 2

    if not args.lane:
        parser.error("--lane is required when building a receipt")
    try:
        metadata = json.loads(args.metadata_json)
    except json.JSONDecodeError as exc:
        raise SystemExit("METADATA_JSON_INVALID") from exc
    if not isinstance(metadata, dict):
        raise SystemExit("METADATA_JSON_MUST_BE_OBJECT")

    receipt = build_receipt(
        lane=args.lane,
        root=root,
        inputs=_files(root, args.input),
        outputs=_files(root, args.output),
        policy_path=(root / args.policy) if args.policy else None,
        metadata=metadata,
    )
    write_receipt(receipt_path, receipt)
    print(json.dumps({"status": "WROTE", "receipt": args.receipt, "receipt_sha256": receipt["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
