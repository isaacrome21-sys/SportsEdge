#!/usr/bin/env python3
"""Run MLB PIT capture locally when GitHub Actions cannot acquire a runner."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, Mapping

from sportsedge.mlb_pit_watch import next_capture_time, publish_data_branch, run_pit_iteration


def _keys() -> list[str]:
    out: list[str] = []
    for name in (
        "SPORTSEDGE_ODDS_API_KEY",
        "SPORTSEDGE_ODDS_API_KEY_2",
        "SPORTSEDGE_ODDS_API_KEY_3",
        "SPORTSEDGE_ODDS_API_KEY_4",
    ):
        value = os.environ.get(name, "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _capture_functions(repo_root: Path):
    from scripts.archive_mlb_prop_odds import build_archive_payload as prop_build
    from scripts.archive_mlb_prop_odds import persist_payload as prop_persist
    from scripts.archive_mlb_additional_odds import build_archive_payload as additional_build
    from scripts.archive_mlb_additional_odds import persist_payload as additional_persist

    keys = _keys()

    def capture_props(now: datetime) -> Mapping[str, Any]:
        payload = prop_build(now=now)
        prop_persist(payload, root=repo_root / "artifacts" / "prop_odds")
        return payload

    def capture_additional(now: datetime) -> Mapping[str, Any]:
        if not keys:
            raise RuntimeError("ODDS_API_KEY_MISSING")
        last_error: Exception | None = None
        for key in keys:
            try:
                payload = additional_build(api_key=key, now=now)
                additional_persist(payload, root=repo_root / "artifacts" / "additional_odds")
                return payload
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise RuntimeError("ODDS_API_KEYRING_EMPTY")

    return capture_props, capture_additional


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--once", action="store_true", help="capture immediately once instead of watching")
    parser.add_argument("--no-publish", action="store_true", help="keep immutable evidence local")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        now = datetime(2026, 8, 26, 13, 7, 1, tzinfo=timezone.utc)
        assert next_capture_time(now).minute == 22
        print(json.dumps({"status": "SELF_TEST_OK", "capture_minutes": [7, 22, 37, 52]}))
        return 0

    root = Path(args.repo_root).resolve()
    capture_props, capture_additional = _capture_functions(root)
    publisher = None if args.no_publish else (lambda: publish_data_branch(root))

    while True:
        now = datetime.now(timezone.utc)
        if not args.once:
            target = next_capture_time(now)
            time.sleep(max(0.0, (target - now).total_seconds()))
            now = datetime.now(timezone.utc)
        result = run_pit_iteration(
            now=now,
            capture_props=capture_props,
            capture_additional=capture_additional,
            publisher=publisher,
        )
        print(json.dumps(result.to_dict(), sort_keys=True), flush=True)
        if args.once:
            return 0 if not result.failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
