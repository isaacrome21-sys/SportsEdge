#!/usr/bin/env python3
"""Stamp current-run NFL 2026 capture records as adjudication-pending.

This never creates or backfills market data. It only annotates capture JSON files
materialized by the current GitHub run while the capture-code delta is awaiting
exact-head reconciliation.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def stamp_current_run(output_dir: Path, policy: dict, github_run_id: str) -> list[str]:
    stamped: list[str] = []
    trigger = str(policy["triggering_merge_sha"])
    for path in sorted(output_dir.glob("week*/opener.json")) + sorted(output_dir.glob("week*/final/*.json")):
        try:
            record = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        run = record.get("run") or {}
        if str(run.get("github_run_id") or "") != str(github_run_id):
            continue
        expected = {
            "status": "ADJUDICATION_PENDING",
            "reason": policy["reason"],
            "triggering_merge_sha": trigger,
            "capture_code_sha": run.get("github_sha"),
            "no_backfill": True,
            "capture_should_continue": True,
            "authority": policy["authority"],
        }
        existing = record.get("adjudication")
        if existing is not None and existing != expected:
            raise SystemExit(f"ADJUDICATION_STAMP_CONFLICT:{path}")
        if existing == expected:
            continue
        record["adjudication"] = expected
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        stamped.append(str(path))
    return stamped


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/nfl_2026_capture.json")
    parser.add_argument("--adjudication-policy", default="config/nfl_2026_capture_adjudication.json")
    parser.add_argument("--github-run-id", default=os.environ.get("GITHUB_RUN_ID"))
    args = parser.parse_args()

    if not args.github_run_id:
        raise SystemExit("GITHUB_RUN_ID_REQUIRED")
    cfg = load_json(Path(args.config))
    policy = load_json(Path(args.adjudication_policy))
    if policy.get("status") != "ADJUDICATION_PENDING":
        print(json.dumps({"status": "NO_STAMP_REQUIRED", "policy_status": policy.get("status")}, sort_keys=True))
        return 0
    stamped = stamp_current_run(Path(cfg["output_dir"]), policy, str(args.github_run_id))
    print(json.dumps({"status": "PASS", "stamped": stamped}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
