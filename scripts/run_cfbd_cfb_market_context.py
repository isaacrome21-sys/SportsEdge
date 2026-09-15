#!/usr/bin/env python3
"""Fetch CFBD CFB lines as context-only market observations."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.cfbd_cfb_market_context import (
    CFBDMarketContextError,
    fetch_cfbd_cfb_market_context,
)


def _utc(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBDMarketContextError("ASOF_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CFBDMarketContextError("ASOF_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def _key() -> str:
    return str(
        os.environ.get("SPORTSEDGE_CFBD_API_KEY")
        or os.environ.get("CFBD_API_KEY")
        or ""
    ).strip()


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--season-type", default="regular")
    parser.add_argument("--asof")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/run_it/cfb_market_context.json"),
    )
    args = parser.parse_args()
    now = _utc(args.asof)
    try:
        snapshot = fetch_cfbd_cfb_market_context(
            year=int(args.season),
            week=int(args.week),
            season_type=str(args.season_type),
            api_key=_key(),
            now=now,
        )
        payload = {
            "schema_version": "SPORTSEDGE_CFBD_CFB_MARKET_CONTEXT_RUN_V1",
            "status": snapshot.disposition,
            "season": int(args.season),
            "week": int(args.week),
            "season_type": str(args.season_type),
            "fetched_at_utc": snapshot.fetched_at_utc,
            "source_native_observed_at": None,
            "payload_sha256": snapshot.payload_sha256,
            "rows": list(snapshot.rows),
            "rejected": list(snapshot.rejected),
            "governance": {
                "market_context_only": True,
                "fetch_time_is_quote_observation": False,
                "ttl_eligible": False,
                "freshness_eligible": False,
                "closing_benchmark_eligible": False,
                "model_p_eligible": False,
                "truth_gate_eligible": False,
                "promotion_authority": False,
                "staking_authority": False,
                "official_authority": False,
            },
        }
        _write(args.output, payload)
        print(json.dumps({
            "status": payload["status"],
            "rows": len(snapshot.rows),
            "rejected": len(snapshot.rejected),
            "output": str(args.output),
        }, sort_keys=True))
        return 0 if snapshot.disposition in {"AVAILABLE", "VALID_NO_BET_SLATE"} else 2
    except CFBDMarketContextError as exc:
        payload = {
            "schema_version": "SPORTSEDGE_CFBD_CFB_MARKET_CONTEXT_RUN_V1",
            "status": "BLOCKED",
            "blocker": str(exc),
            "generated_at_utc": now.isoformat(),
            "governance": {
                "market_context_only": True,
                "fetch_time_is_quote_observation": False,
                "ttl_eligible": False,
                "freshness_eligible": False,
                "closing_benchmark_eligible": False,
                "model_p_eligible": False,
                "truth_gate_eligible": False,
                "promotion_authority": False,
                "staking_authority": False,
                "official_authority": False,
            },
        }
        _write(args.output, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
