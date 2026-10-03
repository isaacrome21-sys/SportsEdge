#!/usr/bin/env python3
"""Emit both NFL sides without editing the frozen auto script.

``scripts/run_nfl_auto.py`` is on the NFL M2 code surface and stays
byte-identical. This wrapper runs that script, then attaches the both-side
prop, side, and total board to the artifact it already wrote.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.nfl_both_side_summary import attach_nfl_auto_payload


def _output_path(args: list[str]) -> Path:
    if "--output" in args:
        index = args.index("--output")
        if index + 1 < len(args):
            return Path(args[index + 1])
    return Path("artifacts/live_nfl_card.json")


def main() -> int:
    args = sys.argv[1:]
    output = _output_path(args)
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/run_nfl_auto.py"), *args],
        cwd=ROOT,
        check=False,
    )
    if output.is_file():
        payload = json.loads(output.read_text(encoding="utf-8"))
    else:
        payload = {
            "schema_version": "NFL_AUTO_RUN_V2",
            "status": "BLOCKED",
            "blocker": "NFL_AUTO_OUTPUT_MISSING",
            "report": {"results": [], "summary": {}},
        }
    attached = attach_nfl_auto_payload(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(attached, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = attached.get("summary") or {}
    print(json.dumps({
        "status": attached.get("status"),
        "both_sides": summary.get("both_sides"),
        "side_rows": summary.get("side_rows"),
        "total_rows": summary.get("total_rows"),
        "prop_rows": summary.get("prop_rows"),
        "catalog_complete": summary.get("catalog_complete"),
        "output": str(output),
        "frozen_auto_exit": int(completed.returncode),
    }, sort_keys=True))
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
