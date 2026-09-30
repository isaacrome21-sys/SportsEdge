#!/usr/bin/env python3
from __future__ import annotations

import argparse, json
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.canonical_manual_mlb import CanonicalManualMLBError, run_canonical_manual_mlb
from sportsedge.manual_mlb_snapshot import run_manual_mlb_snapshot
from sportsedge.manual_quote_live import partition_live_rows, validate_live_rows
from sportsedge.mlb_schedule_filter import filter_schedule_to_game_pk
from sportsedge.mlb_source import GameSnapshot
from sportsedge.runtime import parse_timestamp

# Re-export for tests.test_manual_mlb_live_guards (loads this file as a module).
validate_live_rows = validate_live_rows


def _schedule_snapshot(snapshot) -> list[GameSnapshot] | None:
    if not isinstance(snapshot, dict) or "schedule_snapshot" not in snapshot:
        return None
    raw = snapshot.get("schedule_snapshot")
    if not isinstance(raw, list) or not raw or any(not isinstance(item, dict) for item in raw):
        raise ValueError("MANUAL_SCHEDULE_SNAPSHOT_INVALID")
    try:
        games = [GameSnapshot(**item) for item in raw]
    except (TypeError, ValueError) as exc:
        raise ValueError("MANUAL_SCHEDULE_SNAPSHOT_INVALID") from exc
    if not games:
        raise ValueError("MANUAL_SCHEDULE_SNAPSHOT_INVALID")
    return games


def _empty_payload() -> dict:
    return {
        "schema_version": 2,
        "run_type": "CANONICAL_MANUAL_QUOTES_MULTI_GAME",
        "source": "MANUAL",
        "games": [],
        "results": [],
    }


def _price_game(game_rows, *, history_cache_dir: str, schedule: list[GameSnapshot] | None):
    game_pk = game_rows[0].get("game_pk") if game_rows else None
    if game_pk in (None, ""):
        raise CanonicalManualMLBError("GAME_UNBOUND")
    scoped = filter_schedule_to_game_pk(schedule, game_pk)
    return run_canonical_manual_mlb(game_rows, history_cache_dir=history_cache_dir, schedule=scoped)


def _run_canonical_rows(rows, *, history_cache_dir: str, schedule: list[GameSnapshot] | None = None):
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(str(row.get("game_id")), []).append(row)
    games = []
    results = []
    blocked: list[dict] = []
    last_ok = None
    for game_id, game_rows in grouped.items():
        try:
            payload = _price_game(game_rows, history_cache_dir=history_cache_dir, schedule=schedule)
        except (CanonicalManualMLBError, ValueError) as exc:
            blocked.append({"game_id": game_id, "reason": str(exc)})
            continue
        last_ok = payload
        games.append({
            "input_game_id": game_id,
            "resolved_game": payload.get("resolved_game"),
            "observed_at_utc": payload.get("observed_at_utc"),
            "market_resolution": payload.get("market_resolution", []),
            "feature_lineage": payload.get("feature_lineage", []),
        })
        results.extend(payload.get("results", []))
    if len(grouped) == 1 and not blocked and last_ok is not None:
        return last_ok, blocked
    return {
        "schema_version": 2,
        "run_type": "CANONICAL_MANUAL_QUOTES_MULTI_GAME",
        "source": "MANUAL",
        "games": games,
        "results": results,
    }, blocked


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
    raw_rows = snapshot.get("rows") if isinstance(snapshot, dict) else snapshot if isinstance(snapshot, list) else None
    blocked: list[dict] = []
    notes: list[dict] = []
    rows = raw_rows
    if raw_rows is not None and not args.allow_stale:
        as_of = parse_timestamp(args.as_of) if args.as_of else datetime.now(timezone.utc)
        rows, blocked, notes = partition_live_rows(
            raw_rows, run_date=args.run_date, max_age_minutes=args.max_age_minutes, as_of=as_of,
        )

    schedule = _schedule_snapshot(snapshot)
    extra_blocked: list[dict] = []
    if rows:
        payload, extra_blocked = _run_canonical_rows(
            rows, history_cache_dir=args.history_cache_dir, schedule=schedule,
        )
    elif raw_rows is not None:
        payload = _empty_payload()
    else:
        payload = run_manual_mlb_snapshot(snapshot, history_cache_dir=args.history_cache_dir)
    payload["blocked"] = list(blocked) + list(extra_blocked)
    payload["quote_notes"] = notes
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
