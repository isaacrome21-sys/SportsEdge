#!/usr/bin/env python3
"""Build a source-driven NFL AUTO context slate with no operator game list."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from sportsedge.sports.nfl.auto_slate import build_nfl_auto_context_slate


def _asof(value: str | None) -> datetime:
    if value in (None, ""):
        return datetime.now(timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SystemExit("NFL_AUTO_CONTEXT_ASOF_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise SystemExit("NFL_AUTO_CONTEXT_ASOF_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asof")
    parser.add_argument("--min-lead-minutes", type=int, default=0)
    parser.add_argument("--horizon-minutes", type=int, default=24 * 60)
    parser.add_argument("--game-type", action="append", dest="game_types")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("artifacts/football/nfl_auto_context.json"),
    )
    args = parser.parse_args()
    payload = build_nfl_auto_context_slate(
        as_of=_asof(args.asof),
        mode="AUTO",
        min_lead_minutes=args.min_lead_minutes,
        horizon_minutes=args.horizon_minutes,
        game_types=tuple(args.game_types or ["REG"]),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "as_of_utc": payload["as_of_utc"],
                "collection_mode": payload["collection_mode"],
                "game_count": payload["game_count"],
                "out": str(args.out),
                "model_p_eligible": payload["model_p_eligible"],
                "truth_gate_eligible": payload["truth_gate_eligible"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
