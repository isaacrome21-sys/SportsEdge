#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sportsedge.nhl_lines_intake import NhlLinesIntakeError, parse_nhl_lines, tickets_to_dict

CHICAGO = ZoneInfo("America/Chicago")


def _body_lines(body: str) -> str:
    marker = "### Lines"
    if marker in body:
        body = body.split(marker, 1)[1]
        body = body.split("\n### ", 1)[0]
    return body.replace("```text", "").replace("```", "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--observed-at", required=True)
    ap.add_argument("--issue", required=True)
    ap.add_argument("--out-dir", default="manual_inputs/nhl")
    args = ap.parse_args()
    observed = datetime.fromisoformat(args.observed_at.replace("Z", "+00:00")).astimezone(CHICAGO)
    slate = observed.date().isoformat()
    try:
        tickets = parse_nhl_lines(_body_lines(Path(args.body_file).read_text(encoding="utf-8")))
        payload = tickets_to_dict(tickets, observed_at=observed.isoformat())
        payload["slate"] = slate
        payload["issue"] = args.issue
    except NhlLinesIntakeError as exc:
        Path("intake_error.txt").write_text(str(exc), encoding="utf-8")
        print(f"INTAKE_FAILED: {exc}")
        return 2
    out = Path(args.out_dir) / f"{slate}_issue{args.issue}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"path={out}")
    print(f"slate={slate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
