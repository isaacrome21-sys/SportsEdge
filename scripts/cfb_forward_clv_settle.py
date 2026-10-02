#!/usr/bin/env python3
"""Create-only CFB close settlement using frozen attestation governance.

This command does not create Model_P, evidence eligibility, promotion authority,
or OFFICIAL status. It only resolves raw close snapshots into SELECTED,
PENDING_STABILIZATION, or CLV_MISSING under the frozen policy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.cfb_forward_clv_runtime import CFBForwardRuntimeError, settle_close_group


def _load_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CFBForwardRuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return payload


def _write_once(path: Path, payload: dict[str, object]) -> None:
    if path.exists():
        raise CFBForwardRuntimeError(f"REFUSING_OVERWRITE:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--policy", required=True)
    ap.add_argument("--attestation", required=True)
    ap.add_argument("--raw", action="append", required=True, help="Raw close JSON path; repeat for each snapshot")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    try:
        policy = _load_object(Path(args.policy))
        attestation = _load_object(Path(args.attestation))
        raw_records = [_load_object(Path(p)) for p in args.raw]
        result = settle_close_group(raw_records, attestation_record=attestation, policy=policy)
        result = {
            **result,
            "evidence_class": "SETTLEMENT_RESULT_NOT_PROMOTION_AUTHORITY",
            "promotion_authority": False,
            "model_p_created": False,
            "truth_gate_pass_granted": False,
            "official_status_granted": False,
        }
        _write_once(Path(args.out), result)
    except (OSError, json.JSONDecodeError, CFBForwardRuntimeError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, sort_keys=True))
        return 2

    print(json.dumps(result, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
