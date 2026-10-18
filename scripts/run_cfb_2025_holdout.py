#!/usr/bin/env python3
"""Run the CFB 2025 last-stored-close holdout. Fails closed without a bundle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.holdout_2025 import (  # noqa: E402
    CFB2025HoldoutError,
    grade_cfb_2025_holdout,
    saturday_card_status,
)

DEFAULT_LOCK = ROOT / "config/cfb_2025_holdout_lock_v1.json"
DEFAULT_OUT = ROOT / "artifacts/cfb/cfb_2025_holdout_report.json"


def _load_json(path: Path, code: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(code) from exc
    if not isinstance(payload, dict):
        raise SystemExit(code)
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    ap.add_argument("--bundle", type=Path, default=None)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    lock = _load_json(args.lock, "CFB_HOLDOUT_LOCK_UNREADABLE")
    try:
        phone = saturday_card_status(lock)
    except CFB2025HoldoutError as exc:
        raise SystemExit(str(exc)) from exc

    if args.bundle is None or not args.bundle.exists():
        report = {
            "contract": lock.get("contract"),
            "status": "HOLD_PENDING",
            "phone_card_status": phone,
            "saturday_pricing_allowed": False,
            "promotion_authority": False,
            "blocker": "CFB_2025_HOLDOUT_BUNDLE_NOT_MATERIALIZED",
            "close_semantics": lock.get("close_semantics"),
            "n_rows": 0,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 2

    bundle = _load_json(args.bundle, "CFB_HOLDOUT_BUNDLE_UNREADABLE")
    rows = bundle.get("rows")
    if not isinstance(rows, list):
        raise SystemExit("CFB_HOLDOUT_BUNDLE_ROWS_REQUIRED")
    try:
        graded = grade_cfb_2025_holdout(rows, lock=lock)
    except CFB2025HoldoutError as exc:
        raise SystemExit(str(exc)) from exc
    payload = graded.to_dict()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    if graded.status == "HOLD_FAIL":
        return 3
    if graded.status != "HOLD_PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
