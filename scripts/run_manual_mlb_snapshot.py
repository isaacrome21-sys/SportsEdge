#!/usr/bin/env python3
from __future__ import annotations

import argparse, json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sportsedge.canonical_manual_mlb import run_canonical_manual_mlb
from sportsedge.manual_mlb_snapshot import run_manual_mlb_snapshot
from sportsedge.manual_quote import validate_manual_quote
from sportsedge.runtime import parse_timestamp

CHICAGO_TZ = ZoneInfo("America/Chicago")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def validate_live_rows(rows, *, run_date: str | None, max_age_minutes: int, as_of: datetime) -> None:
    if not isinstance(rows, list) or not rows:
        raise ValueError("MANUAL_INPUT_EMPTY")
    if max_age_minutes <= 0:
        raise ValueError("MANUAL_MAX_AGE_INVALID")
    now = _as_utc(as_of)
    for index, raw in enumerate(rows):
        quote = validate_manual_quote(raw)
        first_pitch_utc = _as_utc(quote.first_pitch_at)
        first_pitch_ct_date = first_pitch_utc.astimezone(CHICAGO_TZ).date().isoformat()
        if run_date and first_pitch_ct_date != run_date:
            raise ValueError(
                f"MANUAL_INPUT_DATE_MISMATCH row={index} expected={run_date} "
                f"first_pitch_date_ct={first_pitch_ct_date}"
            )
        if first_pitch_utc <= now:
            raise ValueError(f"MANUAL_QUOTE_GAME_STARTED row={index} game_id={quote.game_id}")
        observed_utc = _as_utc(quote.observed_at)
        age_minutes = (now - observed_utc).total_seconds() / 60.0
        if age_minutes < 0:
            raise ValueError(f"MANUAL_QUOTE_FROM_FUTURE row={index} game_id={quote.game_id}")
        if age_minutes > max_age_minutes:
            raise ValueError(
                f"MANUAL_QUOTE_STALE row={index} game_id={quote.game_id} "
                f"age_minutes={age_minutes:.1f} max_age_minutes={max_age_minutes}"
            )


def _run_canonical_rows(rows, *, history_cache_dir: str) -> dict:
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(str(row.get("game_id")), []).append(row)
    if len(grouped) == 1:
        return run_canonical_manual_mlb(rows, history_cache_dir=history_cache_dir)
    games = []
    results = []
    for game_id, game_rows in grouped.items():
        payload = run_canonical_manual_mlb(game_rows, history_cache_dir=history_cache_dir)
        games.append({
            "input_game_id": game_id,
            "resolved_game": payload.get("resolved_game"),
            "observed_at_utc": payload.get("observed_at_utc"),
            "market_resolution": payload.get("market_resolution", []),
            "feature_lineage": payload.get("feature_lineage", []),
        })
        results.extend(payload.get("results", []))
    return {
        "schema_version": 2,
        "run_type": "CANONICAL_MANUAL_QUOTES_MULTI_GAME",
        "source": "MANUAL",
        "games": games,
        "results": results,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", default="artifacts/manual_mlb_snapshot_card.json")
    p.add_argument("--history-cache-dir", default=".cache/mlb-history")
    p.add_argument("--run-date", help="Expected Chicago-local first-pitch date (YYYY-MM-DD)")
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
        payload = _run_canonical_rows(snapshot["rows"], history_cache_dir=args.history_cache_dir)
    elif isinstance(snapshot, list):
        payload = _run_canonical_rows(snapshot, history_cache_dir=args.history_cache_dir)
    else:
        payload = run_manual_mlb_snapshot(snapshot, history_cache_dir=args.history_cache_dir)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
