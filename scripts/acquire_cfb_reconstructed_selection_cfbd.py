#!/usr/bin/env python3
"""Acquire hash-bound CFBD inputs for reconstructed CFB candidate selection.

Historical acquisition is allowed only after a VERIFIED private provider preflight.
This script does not fit or score any candidate and creates no Model_P, Truth Gate,
promotion, staking, OFFICIAL, forward-clock, or prospective-backfill authority.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.reconstructed_selection_acquisition import (
    CFBAcquisitionError,
    acquire_plan,
    build_public_manifest,
    build_request_plan,
    load_budget,
    validate_private_preflight,
)

DEFAULT_BUDGET = ROOT / "config/cfb_cfbd_reconstructed_selection_budget_v1.json"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-preflight", type=Path, required=True)
    parser.add_argument("--public-preflight", type=Path, required=True)
    parser.add_argument("--budget", type=Path, default=DEFAULT_BUDGET)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--public-manifest-out", type=Path, required=True)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args(argv)

    try:
        private = json.loads(args.private_preflight.read_text(encoding="utf-8"))
        validate_private_preflight(private)
        budget = load_budget(args.budget)
        plan = build_request_plan(budget)

        if args.plan_only:
            payload = {
                "schema_version": "CFB_RECONSTRUCTED_SELECTION_ACQUISITION_PLAN_V1",
                "status": "PLAN_VERIFIED_NO_NETWORK_CALLS",
                "request_count": len(plan),
                "endpoints": {
                    endpoint: sum(1 for row in plan if row.endpoint == endpoint)
                    for endpoint in sorted({row.endpoint for row in plan})
                },
                "network_calls_performed": 0,
                "attempt_consumed": False,
                "evaluation_performed": False,
                "model_p": False,
                "truth_gate": False,
                "promotion": False,
                "staking": False,
                "official": False,
                "forward_clock": False,
                "prospective_backfill": False,
            }
            _write(args.public_manifest_out, payload)
            print(json.dumps(payload, sort_keys=True))
            return 0

        api_key = str(os.environ.get("CFBD_API_KEY") or "").strip()
        if not api_key:
            raise CFBAcquisitionError("CFBD_API_KEY_MISSING")

        cache_manifest, reused, fetched = acquire_plan(
            plan,
            api_key=api_key,
            cache_root=args.cache_root,
        )
        manifest = build_public_manifest(
            private_preflight_path=args.private_preflight,
            public_preflight_path=args.public_preflight,
            budget_path=args.budget,
            cache_manifest=cache_manifest,
            reused_calls=reused,
            fetched_calls=fetched,
        )
        _write(args.public_manifest_out, manifest)
        print(json.dumps({
            "status": manifest["status"],
            "request_count": len(plan),
            "new_calls_performed": fetched,
            "verified_cache_entries_reused": reused,
            "cache_entry_count": len(cache_manifest),
            "public_manifest": str(args.public_manifest_out),
            "raw_cfbd_responses_persisted_to_public_repository": False,
            "authority": manifest["authority"],
        }, sort_keys=True))
        return 0
    except Exception as exc:
        blocked = {
            "schema_version": "CFB_RECONSTRUCTED_SELECTION_ACQUISITION_PUBLIC_V1",
            "status": "BLOCKED_ACQUISITION",
            "blocker": f"{type(exc).__name__}:{exc}",
            "attempt_consumed": False,
            "evaluation_performed": False,
            "model_p": False,
            "truth_gate": False,
            "promotion": False,
            "staking": False,
            "official": False,
            "forward_clock": False,
            "prospective_backfill": False,
        }
        _write(args.public_manifest_out, blocked)
        print(json.dumps(blocked, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
