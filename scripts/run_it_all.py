#!/usr/bin/env python3
"""Audit or execute every declared SportsEdge RUN IT lane."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Running this file as `python scripts/run_it_all.py` puts only `scripts/` on
# sys.path. Add the repository root explicitly so the canonical `sportsedge`
# package resolves identically in local shells and GitHub Actions.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.run_it_control import audit_surface, execute_surface, scope_from_request


def _request(path: str | None):
    if not path:
        return None
    target = Path(path)
    if not target.exists():
        raise SystemExit("RUN_IT_REQUEST_FILE_MISSING")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit("RUN_IT_REQUEST_FILE_INVALID") from exc
    if not isinstance(payload, dict):
        raise SystemExit("RUN_IT_REQUEST_FILE_INVALID")
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--audit", action="store_true")
    mode.add_argument("--execute", action="store_true")
    ap.add_argument("--scope", default="ALL")
    ap.add_argument("--request")
    ap.add_argument("--output", default="artifacts/run_it/control_plane.json")
    ap.add_argument("--timeout-seconds", type=int, default=900)
    args = ap.parse_args()

    request = _request(args.request)
    if request is not None:
        action = str(request.get("action", "RUN")).strip().upper()
        if action != "RUN":
            raise SystemExit("RUN_IT_REQUEST_ACTION_INVALID")
        scope = scope_from_request(request)
    elif str(args.scope).strip().upper() == "ALL":
        scope = None
    else:
        scope = tuple(x.strip().upper() for x in args.scope.split(",") if x.strip())

    payload = (
        audit_surface()
        if args.audit
        else execute_surface(scope=scope, timeout_seconds=args.timeout_seconds)
    )
    if request is not None:
        payload["request"] = {
            "request_id": request.get("request_id"),
            "requested_at_utc": request.get("requested_at_utc"),
            "scope": request.get("scope", "ALL"),
        }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))

    if args.audit:
        return 0 if payload.get("status") == "PASS" else 2
    # PARTIAL is an honest governed result: some lanes can execute while other
    # declared lanes remain explicit blockers. BROKEN executable lanes return 2.
    broken = any(
        row.get("status") == "BROKEN" for row in payload.get("results", [])
    )
    return 2 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
