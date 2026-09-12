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

from sportsedge.football_prop_surface import FootballPropSurfaceError, require_executable_prop_surface


def _stamp(path: Path):
    """Return an identity/freshness stamp for a child artifact, or ``None``."""
    if not path.is_file():
        return None
    stat = path.stat()
    return (stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)


def _blocked_row(lane: str, reason: str) -> list[dict]:
    return [{
        "market": lane,
        "model_p": None,
        "bet_status": "BLOCKED",
        "reason": reason,
        "run_it_lane": lane,
    }]


def _load(path: Path, lane: str, code: int, previous_stamp) -> tuple[list[dict], dict]:
    """Consume only output proven to have been produced by this child invocation.

    A previous RUN IT card may exist on disk.  If the current child process fails
    before replacing it, that old card must never be re-used as current Model_P.
    Non-zero child exits are also fail-closed even when the child managed to write
    a JSON payload; only its blocker text is retained.
    """
    current_stamp = _stamp(path)
    if current_stamp is None:
        return _blocked_row(lane, f"{lane}_OUTPUT_MISSING"), {}
    if current_stamp == previous_stamp:
        return _blocked_row(lane, f"{lane}_OUTPUT_NOT_REFRESHED"), {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}

    if code != 0:
        blocker = payload.get("blocker") if isinstance(payload, dict) else None
        if not blocker and isinstance(payload, dict):
            report = payload.get("report")
            if isinstance(report, dict):
                blocker = report.get("blocker") or report.get("run_status")
        return _blocked_row(lane, str(blocker or f"{lane}_CHILD_EXIT_{code}")), (
            payload if isinstance(payload, dict) else {}
        )

    report = payload.get("report") if isinstance(payload, dict) else None
    rows = report.get("results") if isinstance(report, dict) else None
    if not isinstance(rows, list):
        blocker = payload.get("blocker") if isinstance(payload, dict) else None
        return _blocked_row(lane, str(blocker or f"{lane}_OUTPUT_INVALID")), (
            payload if isinstance(payload, dict) else {}
        )

    tagged = []
    for raw in rows:
        if isinstance(raw, dict):
            tagged.append({**raw, "run_it_lane": lane})
    if not tagged:
        return _blocked_row(lane, f"{lane}_RESULTS_EMPTY"), payload
    return tagged, payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", required=True, choices=("NFL", "CFB"))
    ap.add_argument("--asof")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    sport = args.sport.upper()
    prop_surface_reason = None
    try:
        require_executable_prop_surface(sport, path=ROOT / "config/football_prop_engine_surface.json")
    except FootballPropSurfaceError as exc:
        # Game Model_P availability is independent of the prop research surface.
        # An explicit NO_ENGINE prop declaration must block only the prop lane,
        # never force RUN IT to discard a valid game-market model result.
        if sport == "NFL" and str(exc) == "FOOTBALL_PROP_ENGINE_NOT_IMPLEMENTED:NFL":
            prop_surface_reason = "NFL_PROPS_NO_ENGINE"
        else:
            raise

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

    game_before = _stamp(game_out)
    game = subprocess.run(game_cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    game_rows, game_payload = _load(game_out, "GAME", game.returncode, game_before)

    if prop_surface_reason:
        prop_rows = _blocked_row("PLAYER_PROPS", prop_surface_reason)
        prop_payload = {
            "status": "NO_ENGINE",
            "blocker": prop_surface_reason,
            "sport": sport,
            "model_p": None,
        }
        prop_returncode = 2
    else:
        prop_before = _stamp(prop_out)
        prop = subprocess.run(prop_cmd, cwd=ROOT, text=True, capture_output=True, check=False)
        prop_returncode = int(prop.returncode)
        prop_rows, prop_payload = _load(prop_out, "PLAYER_PROPS", prop_returncode, prop_before)

    rows = game_rows + prop_rows
    status = (
        "SUCCESS"
        if game.returncode == 0 and prop_returncode == 0
        else "PARTIAL"
        if game.returncode == 0 or prop_returncode == 0
        else "BLOCKED"
    )
    payload = {
        "schema_version": "FOOTBALL_AUTO_BUNDLE_V2",
        "status": status,
        "sport": sport,
        "report": {
            "run_status": status,
            "results": rows,
            "lane_status": {
                "GAME": game_payload.get("status", "BLOCKED"),
                "PLAYER_PROPS": prop_payload.get("status", "BLOCKED"),
            },
            "lane_exit_code": {
                "GAME": int(game.returncode),
                "PLAYER_PROPS": prop_returncode,
            },
        },
        "governance": {
            "model_p_changed": False,
            "truth_gate_changed": False,
            "promotion_changed": False,
            "eligible_changed": False,
            "prop_failures_are_not_silently_skipped": True,
            "prop_no_engine_does_not_block_game_lane": True,
            "stale_child_output_reuse_prohibited": True,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "sport": sport, "output": str(args.output)}, sort_keys=True))
    return 2 if status == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
