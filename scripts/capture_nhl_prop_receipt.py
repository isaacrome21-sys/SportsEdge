#!/usr/bin/env python3
"""Capture one prospective NHL player-prop evidence receipt.

The input is accepted only when it is fresh, pre-puck, inside the frozen forward
window, and contains explicit model/role/source identity.  Output is create-only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from sportsedge.sports.nhl.prop_receipt_capture import (
    NHLPropReceiptError,
    receipt_from_mapping,
    write_create_only,
)


def _load(args: argparse.Namespace) -> dict:
    raw = args.json if args.json is not None else Path(args.input).read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NHLPropReceiptError(f"invalid receipt JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise NHLPropReceiptError("receipt JSON must be an object")
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="path to one JSON receipt object")
    source.add_argument("--json", help="one JSON receipt object")
    parser.add_argument(
        "--output-root",
        default="data/nhl_2026_prop_forward/receipts",
        help="create-only receipt root",
    )
    args = parser.parse_args(argv)

    try:
        receipt = receipt_from_mapping(_load(args))
        path, status = write_create_only(receipt, output_root=args.output_root)
    except (OSError, NHLPropReceiptError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, sort_keys=True))
        return 2

    print(
        json.dumps(
            {
                "status": status,
                "path": str(path),
                "authority": "EVIDENCE_ONLY_NO_CARD_AUTHORITY",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
