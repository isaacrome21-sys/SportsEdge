#!/usr/bin/env python3
"""Pack or restore a Git-safe prospective CFB participation snapshot."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.participation_persistence import (
    DEFAULT_MAX_STORED_BYTES,
    audit_persisted_participation_snapshot,
    pack_participation_snapshot,
    restore_participation_snapshot,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    pack = sub.add_parser("pack")
    pack.add_argument("--capture-root", required=True)
    pack.add_argument("--output-root", required=True)
    pack.add_argument("--max-stored-bytes", type=int, default=DEFAULT_MAX_STORED_BYTES)

    audit = sub.add_parser("audit")
    audit.add_argument("--persisted-root", required=True)

    restore = sub.add_parser("restore")
    restore.add_argument("--persisted-root", required=True)
    restore.add_argument("--output-root", required=True)

    args = parser.parse_args()
    if args.command == "pack":
        report = pack_participation_snapshot(
            capture_root=args.capture_root,
            output_root=args.output_root,
            max_stored_bytes=args.max_stored_bytes,
        )
        summary = {
            "status": "PACKED",
            "schema_version": report["schema_version"],
            "file_count": len(report["files"]),
            "output_root": str(Path(args.output_root)),
            "model_p_created": False,
            "promotion_authority": False,
        }
    elif args.command == "audit":
        summary = audit_persisted_participation_snapshot(args.persisted_root)
    else:
        summary = restore_participation_snapshot(
            persisted_root=args.persisted_root,
            output_root=args.output_root,
        )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
