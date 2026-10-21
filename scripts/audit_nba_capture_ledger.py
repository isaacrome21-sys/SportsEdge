#!/usr/bin/env python3
"""Audit NBA capture and optional prospective ledger, without importing prices.

Examples:
 python scripts/audit_nba_capture_ledger.py --raw-board raw.json --out audit.json
 python scripts/audit_nba_capture_ledger.py --raw-board raw.json --ledger ledger.json --out audit.json
Returns exit code 2 on missing or malformed evidence, never invents an
attestation from caller strings, historical results or a file digest.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.validation.nba_forward_capture_proof import (  # noqa: E402
    audit_capture, NbaCaptureAuditError,
)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-board", required=True)
    ap.add_argument("--ledger")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    try:
        raw = json.loads(Path(args.raw_board).read_text(encoding="utf-8"))
        ledger = (json.loads(Path(args.ledger).read_text(encoding="utf-8"))
                  if args.ledger is not None else None)
        report = audit_capture(raw, ledger)
    except (OSError, json.JSONDecodeError, NbaCaptureAuditError) as exc:
        print(f"NBA_CAPTURE_AUDIT_FAILED:{exc}", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "status", "total_raw_rows", "in_scope_rows", "forward_validation_credit"
    )}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
