#!/usr/bin/env python3
"""Capture diagnostic-only CFB public betting splits.

Writes immutable content-addressed snapshots. Optional previous snapshot comparison
surfaces movement diagnostics. This script never imports or mutates predictive models.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

from sportsedge.market_context.public_splits import (
    PublicSplitsError,
    capture_vsin_cfb,
    compare_snapshots,
    diagnostics,
    snapshot_from_dict,
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PublicSplitsError(f"JSON_READ_FAILED:{path}") from exc
    if not isinstance(value, dict):
        raise PublicSplitsError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _write_immutable(path: Path, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != body:
            raise PublicSplitsError("PUBLIC_SPLIT_IMMUTABLE_COLLISION")
        return
    with path.open("xb") as handle:
        handle.write(body)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture CFB public money/ticket splits")
    parser.add_argument("--config", type=Path, default=Path("config/football_public_splits_v1.json"))
    parser.add_argument("--out-dir", type=Path, default=Path("artifacts/market_context/public_splits"))
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--write-latest", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)

    cfg = _load_json(args.config)
    if (
        cfg.get("diagnostics_only") is not True
        or cfg.get("predictive_model_input") is not False
        or cfg.get("truth_gate_input") is not False
    ):
        raise PublicSplitsError("PUBLIC_SPLIT_CONFIG_MODEL_ISOLATION_REQUIRED")
    source = cfg["sources"]["VSIN_DK"]
    alerts = cfg["alerts"]

    snapshot = capture_vsin_cfb(
        now=datetime.now(timezone.utc),
        source_url=str(source["url"]),
    )
    notable = diagnostics(
        snapshot,
        money_ticket_gap_pp=float(alerts["money_ticket_gap_pp"]),
        public_ticket_pct=float(alerts["public_ticket_pct"]),
    )

    movement: tuple[dict[str, Any], ...] = ()
    if args.previous and args.previous.exists():
        previous = snapshot_from_dict(_load_json(args.previous))
        movement = compare_snapshots(
            previous,
            snapshot,
            public_ticket_pct=float(alerts["public_ticket_pct"]),
            minimum_point_move=float(alerts["minimum_point_move"]),
        )

    report = {
        "contract": "FOOTBALL_PUBLIC_SPLITS_REPORT_V1",
        "snapshot": snapshot.to_dict(),
        "snapshot_hash": snapshot.content_hash(),
        "diagnostics": list(notable),
        "movement": list(movement),
        "model_isolation": {
            "predictive_model_input": False,
            "truth_gate_input": False,
            "usage": "MARKET_CONTEXT_ONLY"
        },
    }
    target = args.out_dir / f"cfb_public_splits_{snapshot.content_hash()}.json"
    _write_immutable(target, report)

    if args.write_latest:
        args.write_latest.parent.mkdir(parents=True, exist_ok=True)
        temp = args.write_latest.with_suffix(args.write_latest.suffix + ".tmp")
        temp.write_text(json.dumps(snapshot.to_dict(), sort_keys=True, indent=2), encoding="utf-8")
        temp.replace(args.write_latest)

    if args.summary:
        print(f"State: {snapshot.state}")
        print(f"Source: {snapshot.source} ({snapshot.source_book})")
        print(f"Captured: {snapshot.captured_at}")
        print(f"Observations: {len(snapshot.observations)}")
        print(f"Notable diagnostics: {len(notable)}")
        print(f"Movement diagnostics: {len(movement)}")
        print(f"Snapshot hash: {snapshot.content_hash()}")
        print(f"Wrote: {target}")
        for row in notable[:20]:
            print(
                f"{row['away_team']} @ {row['home_team']} | {row['market']} {row['side']} "
                f"| money {row['money_pct']:.0f}% / tickets {row['ticket_pct']:.0f}% "
                f"| gap {row['money_ticket_gap_pp']:+.0f}pp | {','.join(row['flags'])}"
            )
        for row in movement[:20]:
            print(
                f"MOVE {row['away_team']} @ {row['home_team']} | {row['market']} {row['side']} "
                f"| {row['previous_line']} -> {row['current_line']} "
                f"| {','.join(row['flags'])}"
            )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PublicSplitsError as exc:
        print(f"PUBLIC_SPLITS_ERROR:{exc}", file=sys.stderr)
        raise SystemExit(2)
