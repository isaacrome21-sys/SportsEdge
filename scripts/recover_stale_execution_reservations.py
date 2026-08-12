#!/usr/bin/env python3
"""Recover only stale RESERVED wager locks; never touch PLACED records."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from sportsedge.execution_reservation import ExecutionReservationError, recover_stale_reservation


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=".cache/sportsedge/execution-reservations")
    p.add_argument("--stale-seconds", type=float, default=900.0)
    p.add_argument("--output", default="artifacts/stale_reservation_recovery.json")
    args = p.parse_args()

    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    recovered = []
    skipped = []
    errors = []

    for path in sorted(root.glob("*.json")):
        wager_key = path.stem
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append({"wager_key": wager_key, "reason": f"MALFORMED_RESERVATION:{type(exc).__name__}"})
            continue
        status = str(row.get("status") or "")
        if status == "PLACED":
            skipped.append({"wager_key": wager_key, "reason": "PLACED_NOT_RECOVERABLE"})
            continue
        if status != "RESERVED":
            skipped.append({"wager_key": wager_key, "reason": f"ACTIVE_FILE_STATUS_{status or 'UNKNOWN'}"})
            continue
        try:
            result = recover_stale_reservation(
                root,
                wager_key,
                max_age_seconds=args.stale_seconds,
                now=now,
            )
            recovered.append({"wager_key": wager_key, "status": result["status"], "detail": result.get("detail")})
        except ExecutionReservationError as exc:
            reason = str(exc)
            if reason == "RESERVATION_NOT_STALE":
                skipped.append({"wager_key": wager_key, "reason": reason})
            else:
                errors.append({"wager_key": wager_key, "reason": reason})

    payload = {
        "schema_version": "sportsedge_stale_reservation_recovery_v1",
        "generated_at_utc": now.isoformat(),
        "stale_seconds": args.stale_seconds,
        "recovered": recovered,
        "skipped": skipped,
        "errors": errors,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
