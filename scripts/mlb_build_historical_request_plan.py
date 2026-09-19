#!/usr/bin/env python3
"""Build a credential-free historical event-odds request plan for MLB replay."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from sportsedge.sports.mlb.historical_event_request_plan import (
    build_historical_event_request_plan,
    canonical_plan_sha256,
)


def _observations(path: Path) -> list[Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, Mapping) and isinstance(payload.get("observations"), list):
        rows = payload["observations"]
    else:
        raise ValueError("PIT_OBSERVATIONS_LIST_REQUIRED")
    if any(not isinstance(row, Mapping) for row in rows):
        raise ValueError("PIT_OBSERVATION_MAPPING_REQUIRED")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pit-observations", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=Path("config/mlb_replay_policy_v1.json"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    if policy.get("policy_id") != "MLB_REPLAY_POLICY_V1" or policy.get("status") != "FROZEN_PRE_REPLAY":
        raise SystemExit("frozen MLB replay policy identity/status mismatch")
    plan = build_historical_event_request_plan(_observations(args.pit_observations), replay_policy=policy)
    plan["plan_sha256"] = canonical_plan_sha256(plan)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "OK",
        "requests": plan["request_count"],
        "source_gaps": plan["source_gap_count"],
        "estimated_max_usage_credits": plan["estimated_max_usage_credits"],
        "out": str(args.out),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
