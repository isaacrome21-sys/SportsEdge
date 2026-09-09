#!/usr/bin/env python3
"""Run one football sport's game and player-prop lanes as a single RUN IT card."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.football_prop_surface import require_executable_prop_surface


def _load(path: Path, lane: str, code: int) -> tuple[list[dict], dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    report = payload.get("report") if isinstance(payload, dict) else None
    rows = report.get("results") if isinstance(report, dict) else None
    if not isinstance(rows, list):
        blocker = payload.get("blocker") if isinstance(payload, dict) else None
        rows = [{
            "market": lane,
            "model_p": None,
            "bet_status": "BLOCKED",
            "reason": str(blocker or f"{lane}_OUTPUT_INVALID"),
        }]
    tagged = []
    for raw in rows:
        if isinstance(raw, dict):
            tagged.append({**raw, "run_it_lane": lane})
    return tagged, payload if isinstance(payload, dict) else {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", required=True, choices=("NFL", "CFB"))
    ap.add_argument("--asof")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    sport = args.sport.upper()
    # This is an actual runtime read, not a decorative config flag. If the
    # authoritative prop surface stops declaring this sport executable, RUN IT
    # fails before trying either child lane.
    require_executable_prop_surface(sport, path=ROOT / "config/football_prop_engine_surface.json")

    lower = sport.lower()
    game_out = ROOT / f"artifacts/run_it/{lower}_game_card.json"
    prop_out = ROOT / f"artifacts/run_it/{lower}_prop_card.json"
    game_cmd = [sys.executable, str(ROOT / f"scripts/run_{lower}_auto.py"), "--output", str(game_out)]
    prop_cmd = [
        sys.executable, str(ROOT / "scripts/run_football_props_auto.py"),
        "--sport", sport, "--output", str(prop_out),
    ]
    if args.asof:
        game_cmd.extend(["--asof", args.asof])
        prop_cmd.extend(["--asof", args.asof])

    game = subprocess.run(game_cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    prop = subprocess.run(prop_cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    game_rows, game_payload = _load(game_out, "GAME", game.returncode)
    prop_rows, prop_payload = _load(prop_out, "PLAYER_PROPS", prop.returncode)
    rows = game_rows + prop_rows
    status = "SUCCESS" if game.returncode == 0 and prop.returncode == 0 else "PARTIAL" if game.returncode == 0 or prop.returncode == 0 else "BLOCKED"
    payload = {
        "schema_version": "FOOTBALL_AUTO_BUNDLE_V1",
        "status": status,
        "sport": sport,
        "report": {
            "run_status": status,
            "results": rows,
            "lane_status": {
                "GAME": game_payload.get("status", "BLOCKED"),
                "PLAYER_PROPS": prop_payload.get("status", "BLOCKED"),
            },
        },
        "governance": {
            "model_p_changed": False,
            "truth_gate_changed": False,
            "promotion_changed": False,
            "eligible_changed": False,
            "prop_failures_are_not_silently_skipped": True,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "sport": sport, "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
