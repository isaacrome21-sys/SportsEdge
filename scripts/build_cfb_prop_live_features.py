#!/usr/bin/env python3
"""Build strict CFB prop live features from an already captured PIT usage file."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.prop_manual_depth import (
    bind_manual_depth_to_live_features,
    load_manual_depth_input,
)
from sportsedge.sports.cfb.prop_usage_input import (
    CFBPropUsageInputError,
    build_live_features,
    load_usage_input,
)


def _utc(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    text = value.strip().replace("Z", "+00:00")
    out = datetime.fromisoformat(text)
    if out.tzinfo is None or out.utcoffset() is None:
        raise ValueError("CFB_PROP_USAGE_NOW_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--usage-input", type=Path, required=True)
    ap.add_argument("--manual-depth", type=Path)
    ap.add_argument("--asof")
    ap.add_argument("--max-age-seconds", type=int, default=7200)
    ap.add_argument(
        "--output", type=Path,
        default=Path("artifacts/football/cfb_prop_live_features.json"),
    )
    args = ap.parse_args()
    try:
        payload, raw_sha = load_usage_input(args.usage_input)
        live = build_live_features(
            payload=payload,
            input_bytes_sha256=raw_sha,
            now=_utc(args.asof),
            max_age_seconds=int(args.max_age_seconds),
        )
        if args.manual_depth is not None:
            depth, depth_sha = load_manual_depth_input(args.manual_depth)
            live = bind_manual_depth_to_live_features(
                live_features=live,
                manual_input=depth,
                manual_bytes_sha256=depth_sha,
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(live, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps({
            "status": "SUCCESS",
            "output": str(args.output),
            "games": len(live["games"]),
            "promotion_authority": False,
        }, sort_keys=True))
        return 0
    except (CFBPropUsageInputError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "blocker": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
