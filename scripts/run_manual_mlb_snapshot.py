#!/usr/bin/env python3
from __future__ import annotations

import argparse, json
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.canonical_manual_mlb import run_canonical_manual_mlb
from sportsedge.manual_mlb_snapshot import run_manual_mlb_snapshot
from sportsedge.manual_quote import validate_manual_quote
from sportsedge.runtime import parse_timestamp


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def validate_live_rows(rows, *, run_date: str | None, max_age_minutes: int, as_of: datetime) -> None:
    if not isinstance(rows, list) or not rows:
        raise ValueError("MANUAL_INPUT_EMPTY")
    now = _as_utc(as_of)
    for index, raw in enumerate(rows):
        quote = validate_manual_quote(raw)
        if run_date and quote.first_pitch_at.date().isoformat() != run_date:
            raise ValueError(
                f"MANUAL_INPUT_DATE_MISMATCH row={index} expected={run_date} "
                f"first_pitch_date={quote.first_pitch_at.date().isoformat()}"
            )
        if _as_utc(quote.first_pitch_at) <= now:
            raise ValueError(f"MANUAL_QUOTE_GAME_STARTED row={index} game_id={quote.game_id}")
        age_minutes = (now - _as_utc(quote.observed_at)).total_seconds() / 60.0
        if age_minutes < 0:
            raise ValueError(f"MANUAL_QUOTE_FROM_FUTURE row={index} game_id={quote.game_id}")
        if age_minutes > max_age_minutes:
            raise ValueError(
                f"MANUAL_QUOTE_STALE row={index} game_id={quote.game_id} "
                f"age_minutes={age_minutes:.1f} max_age_minutes={max_age_minutes}"
            )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", default="artifacts/manual_mlb_snapshot_card.json")
    p.add_argument("--history-cache-dir", default=".cache/mlb-history")
    p.add_argument("--run-date", help="Expected local first-pitch date (YYYY-MM-DD)")
    p.add_argument("--max-age-minutes", type=int, default=30)
    p.add_argument("--as-of", help="Override current time for deterministic regression tests")
    p.add_argument("--allow-stale", action="store_true", help="Regression fixtures only; bypass live date/recency gates")
    args = p.parse_args()

    snapshot = json.loads(Path(args.input).read_text())
    rows = snapshot.get("rows") if isinstance(snapshot, dict) else snapshot if isinstance(snapshot, list) else None
    if rows is not None and not args.allow_stale:
        as_of = parse_timestamp(args.as_of) if args.as_of else datetime.now(timezone.utc)
        validate_live_rows(rows, run_date=args.run_date, max_age_minutes=args.max_age_minutes, as_of=as_of)

    if isinstance(snapshot, dict) and isinstance(snapshot.get("rows"), list):
        payload = run_canonical_manual_mlb(snapshot["rows"], history_cache_dir=args.history_cache_dir)
    elif isinstance(snapshot, list):
        payload = run_canonical_manual_mlb(snapshot, history_cache_dir=args.history_cache_dir)
    else:
        payload = run_manual_mlb_snapshot(snapshot, history_cache_dir=args.history_cache_dir)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
