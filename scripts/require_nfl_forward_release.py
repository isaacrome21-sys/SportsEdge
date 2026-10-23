#!/usr/bin/env python3
"""Visible, fail-closed NFL forward collector refusal when no frozen release exists.

This is a health/status gate only. It never touches evidence, fetches prices,
changes freeze identities, creates decisions/closes, or backfills a window.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


def _code(value: object, default: str) -> str:
    if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", value):
        return value
    return default


def refuse_missing_production_release(status_file: Path, summary_file: Path | None = None) -> int:
    try:
        data = json.loads(status_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    state = _code(data.get("state"), "RELEASE_STATUS_MISSING_OR_INVALID")
    freeze = _code(data.get("freeze_status"), "UNKNOWN")
    notice = (
        f"NFL_FORWARD_COLLECTION_BLOCKED:{state}:freeze={freeze}; "
        "no frozen, verified model release; no decisions, closes or coverage credited"
    )
    if summary_file is not None:
        with summary_file.open("a", encoding="utf-8") as handle:
            handle.write(
                "## NFL forward CLV — BLOCKED, not collected\n\n"
                f"**Cause:** {state} (freeze: {freeze}).\n\n"
                "No production decisions or closing quotes were captured by this run. "
                "Covered-game count does not increase; missed windows cannot be backfilled.\n"
            )
    print(f"::error title=NFL forward collection blocked::{notice}", flush=True)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-file", type=Path, required=True)
    args = parser.parse_args()
    path = Path(os.environ["GITHUB_STEP_SUMMARY"]) if os.environ.get("GITHUB_STEP_SUMMARY") else None
    return refuse_missing_production_release(args.status_file, path)


if __name__ == "__main__":
    raise SystemExit(main())
