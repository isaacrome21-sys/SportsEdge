#!/usr/bin/env python3
"""Pull-based health check for durable NRFI/YRFI validation evidence.

This checker intentionally inspects persisted data-branch files rather than workflow
status. It distinguishes execution timestamps from actual evidence timestamps so
re-running settlement cannot make stale evidence look fresh.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def newest_prediction_time(report: dict[str, Any]) -> datetime | None:
    values = []
    for row in report.get("game_evidence") or []:
        value = (row or {}).get("generated_at_utc")
        if value:
            values.append(parse_dt(value))
    return max(values) if values else None


def newest_settlement_time(settlements: list[dict[str, Any]]) -> datetime | None:
    values = []
    for row in settlements:
        value = (row or {}).get("settled_at_utc")
        if value:
            values.append(parse_dt(value))
    return max(values) if values else None


def newest_durable_capture_time(root: Path) -> datetime | None:
    values = []
    captures = root / "captures"
    if not captures.exists():
        return None
    for path in captures.rglob("nrfi_v6_status.json"):
        try:
            status = load_json(path)
            value = status.get("generated_at_utc")
            if value:
                values.append(parse_dt(value))
        except Exception:
            continue
    return max(values) if values else None


def hours_old(now: datetime, value: datetime | None) -> float | None:
    return None if value is None else (now - value).total_seconds() / 3600.0


def check(root: Path, now: datetime, max_capture_age_hours: float, max_settlement_age_hours: float) -> dict[str, Any]:
    latest = root / "latest"
    report_path = latest / "nrfi_v6_forward_shadow_report.json"
    manifest_path = latest / "nrfi_v6_forward_shadow_manifest.json"
    settlement_path = latest / "nrfi_v6_settlements.json"
    for path in (report_path, manifest_path, settlement_path):
        if not path.is_file() or path.stat().st_size == 0:
            raise SystemExit(f"NRFI_DURABLE_MISSING:{path}")

    report = load_json(report_path)
    manifest = load_json(manifest_path)
    settlements = load_json(settlement_path)
    if not isinstance(settlements, list):
        raise SystemExit("NRFI_DURABLE_BAD_SETTLEMENT_LEDGER")

    if manifest.get("report_sha256") != sha256(report_path):
        raise SystemExit("NRFI_DURABLE_REPORT_SHA_MISMATCH")
    if manifest.get("settlement_sha256") != sha256(settlement_path):
        raise SystemExit("NRFI_DURABLE_SETTLEMENT_SHA_MISMATCH")
    if manifest.get("candidate_sha256") != report.get("candidate_sha256"):
        raise SystemExit("NRFI_DURABLE_CANDIDATE_SHA_MISMATCH")

    nrfi_eligible = bool(((report.get("markets") or {}).get("NRFI") or {}).get("eligible"))
    yrfi_eligible = bool(((report.get("markets") or {}).get("YRFI") or {}).get("eligible"))
    if nrfi_eligible != yrfi_eligible or bool(manifest.get("eligible")) != nrfi_eligible:
        raise SystemExit("NRFI_DURABLE_ELIGIBILITY_MISMATCH")

    ids = [str((row or {}).get("game_id") or "") for row in settlements]
    ids = [x for x in ids if x]
    if len(ids) != len(set(ids)):
        raise SystemExit("NRFI_DURABLE_DUPLICATE_SETTLEMENT_GAME")
    if int(report.get("settled_unique_games") or 0) != len(ids):
        raise SystemExit("NRFI_DURABLE_SETTLED_COUNT_MISMATCH")

    prediction_time = newest_prediction_time(report)
    capture_time = newest_durable_capture_time(root)
    settlement_time = newest_settlement_time(settlements)
    effective_capture_time = max([x for x in (prediction_time, capture_time) if x is not None], default=None)

    capture_age = hours_old(now, effective_capture_time)
    settlement_age = hours_old(now, settlement_time)
    problems = []
    if effective_capture_time is None:
        problems.append("NO_DURABLE_CAPTURE_TIME")
    elif capture_age is not None and capture_age > max_capture_age_hours:
        problems.append("CAPTURE_STALE")
    if settlement_time is None:
        problems.append("NO_DURABLE_SETTLEMENT_TIME")
    elif settlement_age is not None and settlement_age > max_settlement_age_hours:
        problems.append("SETTLEMENT_STALE")

    state = "HEALTHY" if not problems else "STALE"
    return {
        "state": state,
        "problems": problems,
        "report_generated_at_utc": report.get("generated_at_utc"),
        "newest_prediction_generated_at_utc": prediction_time.isoformat() if prediction_time else None,
        "newest_durable_capture_generated_at_utc": capture_time.isoformat() if capture_time else None,
        "newest_settlement_at_utc": settlement_time.isoformat() if settlement_time else None,
        "capture_age_hours": capture_age,
        "settlement_age_hours": settlement_age,
        "settled_unique_games": int(report.get("settled_unique_games") or 0),
        "selected_unique_games": int(report.get("selected_unique_games") or 0),
        "model_state": report.get("state"),
        "eligible": nrfi_eligible,
        "candidate_sha256": report.get("candidate_sha256"),
        "feature_contract_sha256": report.get("feature_contract_sha256"),
        "integrity_violations": list((((report.get("gates") or {}).get("integrity") or {}).get("violations")) or []),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", default="runtime/model-validation/NRFI_YRFI")
    ap.add_argument("--now")
    ap.add_argument("--max-capture-age-hours", type=float, default=36.0)
    ap.add_argument("--max-settlement-age-hours", type=float, default=36.0)
    args = ap.parse_args()
    now = parse_dt(args.now) if args.now else datetime.now(timezone.utc)
    result = check(Path(args.data_root), now, args.max_capture_age_hours, args.max_settlement_age_hours)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["state"] == "HEALTHY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
