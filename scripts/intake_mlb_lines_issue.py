#!/usr/bin/env python3
"""Issue body -> manual_inputs/mlb/<slate>_issue<N>.json (no agent in the loop)."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.mlb_lines_intake import LinesIntakeError, build_input  # noqa: E402
from sportsedge.mlb_source import fetch_schedule  # noqa: E402

CHICAGO = ZoneInfo("America/Chicago")


def _body_lines(body: str) -> str:
    # Issue forms wrap the textarea under a "### Lines" heading.
    marker = "### Lines"
    if marker in body:
        body = body.split(marker, 1)[1]
        body = body.split("\n### ", 1)[0]
    return body.replace("```text", "").replace("```", "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--observed-at", required=True, help="issue created/edited timestamp (ISO 8601)")
    ap.add_argument("--issue", required=True)
    ap.add_argument("--out-dir", default="manual_inputs/mlb")
    args = ap.parse_args()

    observed = datetime.fromisoformat(args.observed_at.replace("Z", "+00:00")).astimezone(CHICAGO)
    slate = observed.date().isoformat()
    body = _body_lines(Path(args.body_file).read_text(encoding="utf-8"))
    try:
        schedule = fetch_schedule(slate)
        payload = build_input(body, observed_at=observed.isoformat(), schedule=schedule)
        # Reuse the exact live schedule response that bound the phone text to MLB games.
        # This snapshot is run-local evidence only; it is not persisted as a cross-run cache.
        payload["schedule_snapshot"] = [asdict(game) for game in schedule]
    except LinesIntakeError as exc:
        Path("intake_error.txt").write_text(str(exc), encoding="utf-8")
        print(f"INTAKE_FAILED: {exc}", file=sys.stderr)
        return 2
    out = Path(args.out_dir) / f"{slate}_issue{args.issue}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"path={out}")
    print(f"slate={slate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
