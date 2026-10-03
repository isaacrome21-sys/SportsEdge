#!/usr/bin/env python3
"""Issue body -> manual_inputs/mlb/<slate>_issue<N>.json (no agent in the loop)."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.mlb_issue_body import IssueLinesError, extract_issue_lines  # noqa: E402
from sportsedge.mlb_lines_intake import LinesIntakeError  # noqa: E402
from sportsedge.mlb_resolve import build_bound_input  # noqa: E402
from sportsedge.mlb_source import fetch_schedule  # noqa: E402

CHICAGO = ZoneInfo("America/Chicago")

# Phone-issue research hooks (same pattern as the CFB {"backtest": ...} board):
# a fenced body whose first line is "RESEARCH <name>" runs a pre-registered
# validation and posts its report on the issue. No lines are read and no card is run.
RESEARCH_DIRECTIVES = {
    "pitcher_prior_fallback": "scripts/research_mlb_pitcher_prior_fallback.py",
}


def research_directive(body: str) -> str | None:
    first = (body.strip().splitlines() or [""])[0].strip()
    parts = first.split()
    if len(parts) == 2 and parts[0].upper() == "RESEARCH":
        name = parts[1].lower()
        if name not in RESEARCH_DIRECTIVES:
            raise IssueLinesError(f"MLB_UNKNOWN_RESEARCH_DIRECTIVE {name}; known: {', '.join(sorted(RESEARCH_DIRECTIVES))}")
        return name
    return None


def run_research(name: str, issue: str) -> int:
    import subprocess
    import traceback

    root = Path(__file__).resolve().parents[1]
    out_dir = Path("artifacts") / f"mlb_research_{name}"
    try:
        proc = subprocess.run([sys.executable, str(root / RESEARCH_DIRECTIVES[name]), "--out-dir", str(out_dir)],
                              capture_output=True, text=True, timeout=11 * 60)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout)[-3000:])
        subprocess.run(["gh", "issue", "comment", str(issue), "--body-file", str(out_dir / "report.md")], check=True)
        msg = f"RESEARCH_DIRECTIVE_DONE {name}: report posted above. This was a research run, not a lines board."
    except Exception:  # surface the failure on the issue instead of a silent red job
        msg = f"RESEARCH_DIRECTIVE_FAILED {name}:\n{traceback.format_exc()[-3000:]}"
    Path("intake_error.txt").write_text(msg, encoding="utf-8")
    print(msg, file=sys.stderr)
    return 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--observed-at", required=True, help="issue created/edited timestamp (ISO 8601)")
    ap.add_argument("--issue", required=True)
    ap.add_argument("--out-dir", default="manual_inputs/mlb")
    args = ap.parse_args()

    observed = datetime.fromisoformat(args.observed_at.replace("Z", "+00:00")).astimezone(CHICAGO)
    slate = observed.date().isoformat()
    try:
        body = extract_issue_lines(Path(args.body_file).read_text(encoding="utf-8"))
    except IssueLinesError as exc:
        Path("intake_error.txt").write_text(str(exc), encoding="utf-8")
        print(f"INTAKE_FAILED: {exc}", file=sys.stderr)
        return 2
    try:
        directive = research_directive(body)
    except IssueLinesError as exc:
        Path("intake_error.txt").write_text(str(exc), encoding="utf-8")
        return 2
    if directive:
        return run_research(directive, args.issue)
    try:
        nxt = (observed.date() + timedelta(days=1)).isoformat()
        schedule = list(fetch_schedule(slate)) + list(fetch_schedule(nxt))
        payload = build_bound_input(body, observed_at=observed.isoformat(), schedule=schedule)
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
