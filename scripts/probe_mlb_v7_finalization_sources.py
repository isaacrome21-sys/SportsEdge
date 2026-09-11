#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from sportsedge.mlb_v7_travel_history import BASE, _get_json, write_json


def _collect_timestamp_like(value: Any, path: str = "") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            lower = str(key).lower()
            if any(token in lower for token in ("timestamp", "timeStamp".lower(), "updated", "modified", "endtime", "end_time", "date")):
                if isinstance(child, (str, int, float, bool)) or child is None:
                    out.append({"path": child_path, "value": child})
            out.extend(_collect_timestamp_like(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value[:50]):
            out.extend(_collect_timestamp_like(child, f"{path}[{index}]"))
    return out


def _status_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    game_data = payload.get("gameData") or {}
    status = game_data.get("status") or payload.get("status") or {}
    meta = payload.get("metaData") or {}
    return {
        "gameData_status": status,
        "metaData": meta,
        "timestamp_like": _collect_timestamp_like(payload)[:200],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe official MLB endpoints for immutable game-finalization timestamps.")
    parser.add_argument("--game-id", type=int, default=778485)
    parser.add_argument("--output-root", default="artifacts/mlb-v7-finalization-probe")
    args = parser.parse_args()
    root = Path(args.output_root)
    endpoints = {
        "live_v11": f"{BASE}/api/v1.1/game/{args.game_id}/feed/live",
        "live_v1": f"{BASE}/api/v1/game/{args.game_id}/feed/live",
        "content": f"{BASE}/api/v1/game/{args.game_id}/content",
        "boxscore": f"{BASE}/api/v1/game/{args.game_id}/boxscore",
        "linescore": f"{BASE}/api/v1/game/{args.game_id}/linescore",
    }
    report: dict[str, Any] = {
        "contract": "SPORTSEDGE_MLB_V7_FINALIZATION_SOURCE_PROBE_V1",
        "game_id": args.game_id,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "promotion_authority": False,
        "candidate_training_allowed": False,
        "fallback_authorized": False,
        "sources": {},
    }
    for name, url in endpoints.items():
        try:
            payload = _get_json(url)
            sha = write_json(root / f"raw/{name}.json", payload)
            summary = _status_summary(payload)
            summary.update({"url": url, "sha256": sha, "fetch_state": "PASS"})
            report["sources"][name] = summary
        except Exception as exc:
            report["sources"][name] = {"url": url, "fetch_state": "BLOCKED", "reason": f"{type(exc).__name__}:{exc}"}
    write_json(root / "report.json", report)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
