#!/usr/bin/env python3
"""Classify CFBD market-context execution health without weakening fail-closed domain status."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SCHEMA = "SPORTSEDGE_CFBD_CFB_MARKET_CONTEXT_RUN_V1"
HEALTHY = {"AVAILABLE", "VALID_NO_BET_SLATE"}
BLOCKED = {"BLOCKED", "BLOCKED_NO_ODDS", "NO_ELIGIBLE_QUOTES"}


def classify(payload: dict, engine_exit_code: int) -> dict:
    status = str(payload.get("status") or "")
    schema = str(payload.get("schema_version") or "")
    valid_schema = schema == SCHEMA
    if valid_schema and engine_exit_code == 0 and status in HEALTHY:
        op = "HEALTHY"
        ok = True
    elif valid_schema and engine_exit_code != 0 and status in BLOCKED:
        op = "HEALTHY_DOMAIN_BLOCKED"
        ok = True
    else:
        op = "OPERATIONAL_FAILURE"
        ok = False
    return {
        "schema_version": "SPORTSEDGE_CFB_MARKET_CONTEXT_OPERATION_V1",
        "operational_status": op,
        "operationally_healthy": ok,
        "domain_status": status or None,
        "domain_blocked": status in BLOCKED,
        "engine_exit_code": int(engine_exit_code),
        "source_artifact_schema_valid": valid_schema,
        "model_p_authority": False,
        "truth_gate_authority": False,
        "promotion_authority": False,
        "official_authority": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", type=Path, required=True)
    ap.add_argument("--engine-exit-code", type=int, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    try:
        raw = args.artifact.read_text(encoding="utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("ARTIFACT_NOT_OBJECT")
        result = classify(payload, args.engine_exit_code)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        result = {
            "schema_version": "SPORTSEDGE_CFB_MARKET_CONTEXT_OPERATION_V1",
            "operational_status": "OPERATIONAL_FAILURE",
            "operationally_healthy": False,
            "domain_status": None,
            "domain_blocked": False,
            "engine_exit_code": int(args.engine_exit_code),
            "artifact_error": f"{type(exc).__name__}:{exc}",
            "model_p_authority": False,
            "truth_gate_authority": False,
            "promotion_authority": False,
            "official_authority": False,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["operationally_healthy"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
