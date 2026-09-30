#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sportsedge.cfb_lines_intake import CfbLinesIntakeError, parse_cfb_lines, tickets_to_dict

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
    args = ap.parse_args()
    body = Path(args.body_file).read_text(encoding="utf-8")
    try:
        tickets = parse_cfb_lines(_body_lines(body))
    except CfbLinesIntakeError as exc:
        Path("intake_error.txt").write_text(str(exc), encoding="utf-8")
        return 1
    observed = args.observed_at
    try:
        observed = datetime.fromisoformat(observed.replace("Z", "+00:00")).astimezone(CHICAGO).isoformat()
    except ValueError:
        pass
    payload = tickets_to_dict(tickets, observed_at=observed)
    payload["issue"] = args.issue
    out = Path("artifacts/cfb_myspari")
    out.mkdir(parents=True, exist_ok=True)
    path = out / "snapshot.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"path={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
