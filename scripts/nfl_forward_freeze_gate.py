#!/usr/bin/env python3
"""Cheap pre-spend freeze gate for the NFL forward CLV collector (t215u Option A).

``check``: validates ``config/nfl_m2_freeze.json``. FROZEN + 64-hex hash ->
``frozen=true`` (the collector proceeds on this very run). Valid UNFROZEN ->
``frozen=false`` and a per-America/Chicago-day marker key; quiet success.
Missing or invalid freeze -> visible failure (never skipped).

``daily``: decides whether this blocked run is the one visible daily failure.
Scheduled runs report only when the day's no-secret actions/cache marker is
absent (first blocked scheduled run of each CT calendar day); manual dispatches
always report.

Status only: no provider calls, no evidence writes, no backfill, no governance
change. Uses stdlib only so it runs on the stock runner python3.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")
MARKER_PREFIX = "nfl-forward-m2-unfrozen-daily-"
HEX64 = re.compile(r"[0-9a-f]{64}")


class FreezeInvalid(Exception):
    pass


def classify(path: Path) -> bool:
    """Return True when verified FROZEN, False when valid UNFROZEN; raise otherwise."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FreezeInvalid("FREEZE_FILE_MISSING") from exc
    except OSError as exc:
        raise FreezeInvalid("FREEZE_FILE_MISSING") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise FreezeInvalid("FREEZE_FILE_INVALID") from exc
    if not isinstance(data, dict):
        raise FreezeInvalid("FREEZE_FILE_INVALID")
    if data.get("schema_version") != 1 or data.get("hash_algorithm") != "CANONICAL_JSON_SHA256_V1":
        raise FreezeInvalid("FREEZE_FILE_INVALID")
    if not isinstance(data.get("artifact_path"), str) or not data["artifact_path"]:
        raise FreezeInvalid("FREEZE_FILE_INVALID")
    status = data.get("status")
    digest = data.get("artifact_sha256")
    if status == "FROZEN":
        if not isinstance(digest, str) or not HEX64.fullmatch(digest):
            raise FreezeInvalid("FREEZE_FILE_INVALID")
        return True
    if status == "UNFROZEN":
        if digest is not None:
            raise FreezeInvalid("FREEZE_FILE_INVALID")
        return False
    raise FreezeInvalid("FREEZE_FILE_INVALID")


def ct_date(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(CT).date().isoformat()


def should_report(event: str, marker_hit: str) -> bool:
    if event == "schedule":
        return marker_hit != "true"
    return True


def _emit(outputs: dict[str, str]) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    lines = "".join(f"{k}={v}\n" for k, v in outputs.items())
    if target:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(lines)
    sys.stdout.write(lines)


def _fail(code: str) -> int:
    notice = f"NFL_FORWARD_COLLECTION_BLOCKED:{code}"
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(
                "## NFL forward CLV — BLOCKED, freeze file not verifiable\n\n"
                f"**Cause:** {code}.\n\nNo provider request, quota probe, download or "
                "evidence write was attempted. Nothing is backfilled.\n"
            )
    print(f"::error title=NFL forward collection blocked::{notice}", flush=True)
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--freeze", type=Path, default=Path("config/nfl_m2_freeze.json"))
    c.add_argument("--now")
    d = sub.add_parser("daily")
    d.add_argument("--event", required=True)
    d.add_argument("--marker-hit", default="")
    args = ap.parse_args(argv)
    if args.cmd == "daily":
        _emit({"report": "true" if should_report(args.event, args.marker_hit) else "false"})
        return 0
    try:
        frozen = classify(args.freeze)
    except FreezeInvalid as exc:
        _emit({"frozen": "invalid"})
        return _fail(str(exc))
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc)
    day = ct_date(now)
    _emit({"frozen": "true" if frozen else "false", "ct_date": day, "marker_key": MARKER_PREFIX + day})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
