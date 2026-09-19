#!/usr/bin/env python3
"""Bind a fetched provider response to one request-plan row and archive it."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from sportsedge.sports.mlb.historical_event_snapshot_ingest import ingest_historical_event_response


def _plan(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping) or not isinstance(value.get("requests"), list):
        raise ValueError("REQUEST_PLAN_INVALID")
    return value


def _request(plan: Mapping[str, Any], request_id: str) -> Mapping[str, Any]:
    matches = [row for row in plan["requests"] if isinstance(row, Mapping) and str(row.get("request_id") or "") == request_id]
    if len(matches) != 1:
        raise ValueError(f"REQUEST_ID_MATCH_COUNT:{len(matches)}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--response", type=Path, required=True, help="Exact raw JSON response bytes from provider")
    parser.add_argument("--archive-root", type=Path, required=True)
    args = parser.parse_args()

    plan = _plan(args.plan)
    result = ingest_historical_event_response(
        args.response.read_bytes(),
        request_descriptor=_request(plan, args.request_id),
        archive_root=args.archive_root,
        plan=plan,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
