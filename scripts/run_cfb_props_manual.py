#!/usr/bin/env python3
"""Run CFB props with explicit manual/phone PIT depth evidence and manual odds.

The wrapper only strengthens the existing frozen CFB prop runtime. It validates
and hash-binds manual depth evidence to an already-existing numeric usage feature
snapshot, then invokes the canonical football prop runner. It never derives usage
shares from depth order and never sends a paid odds request.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.prop_manual_depth import (
    CFBPropManualDepthError,
    bind_manual_depth_to_live_features,
    load_manual_depth_input,
)


class CFBPropManualRunError(ValueError):
    pass


def _json(path: Path, code: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CFBPropManualRunError(code) from exc
    if not isinstance(value, dict):
        raise CFBPropManualRunError(code)
    return value


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--depth-input", type=Path, required=True)
    ap.add_argument("--live-features", type=Path, required=True)
    ap.add_argument("--odds-snapshot", type=Path, required=True)
    ap.add_argument("--asof")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--n-paths", type=int, default=20000)
    ap.add_argument("--root-seed", type=int, default=20260909)
    args = ap.parse_args()

    bound_path = ROOT / "artifacts/run_it/cfb_prop_live_features_depth_bound.json"
    try:
        if not args.odds_snapshot.is_file():
            raise CFBPropManualRunError("CFB_PROP_MANUAL_ODDS_SNAPSHOT_REQUIRED")
        live = _json(args.live_features, "CFB_PROP_MANUAL_LIVE_FEATURES_INVALID")
        manual, manual_sha = load_manual_depth_input(args.depth_input)
        bound = bind_manual_depth_to_live_features(
            live_features=live,
            manual_input=manual,
            manual_bytes_sha256=manual_sha,
        )
        _write(bound_path, bound)
    except (CFBPropManualDepthError, CFBPropManualRunError) as exc:
        payload = {
            "schema_version": "CFB_PROP_MANUAL_RUN_V1",
            "status": "BLOCKED",
            "blocker": str(exc),
            "report": {
                "run_status": "BLOCKED",
                "results": [{
                    "sport": "CFB", "market": "FOOTBALL_PLAYER_PROPS",
                    "model_p": None, "bet_status": "BLOCKED", "reason": str(exc),
                }],
            },
            "governance": {
                "paid_odds_api_used": False,
                "depth_used_to_invent_usage": False,
                "promotion_authority": False,
            },
        }
        _write(args.output, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2

    cmd = [
        sys.executable,
        str(ROOT / "scripts/run_football_props_auto.py"),
        "--sport", "CFB",
        "--live-features", str(bound_path),
        "--odds-snapshot", str(args.odds_snapshot),
        "--n-paths", str(int(args.n_paths)),
        "--root-seed", str(int(args.root_seed)),
        "--output", str(args.output),
    ]
    if args.asof:
        cmd.extend(["--asof", args.asof])
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
