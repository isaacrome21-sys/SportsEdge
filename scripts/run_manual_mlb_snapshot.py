#!/usr/bin/env python3
from __future__ import annotations

import argparse, json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sportsedge.canonical_manual_mlb import run_canonical_manual_mlb
from sportsedge.manual_mlb_snapshot import run_manual_mlb_snapshot
from sportsedge.manual_quote import ManualQuoteError, validate_manual_quote
from sportsedge.mlb_source import GameSnapshot
from sportsedge.runtime import parse_timestamp

CHICAGO_TZ = ZoneInfo("America/Chicago")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def partition_live_rows(rows, *, run_date: str | None, max_age_minutes: int | None, as_of: datetime):
    if not isinstance(rows, list) or not rows:
        raise ValueError("MANUAL_INPUT_EMPTY")
    if max_age_minutes <= 0:
        raise ValueError("MANUAL_MAX_AGE_INVALID")
    now = _as_utc(as_of)
    allowed = set()
    if run_date:
        start = datetime.fromisoformat(run_date).date()
        allowed = {start.isoformat(), (start + timedelta(days=1)).isoformat()}
    live: list = []
    blocked: list[dict] = []
    for index, raw in enumerate(rows):
        game_id = str((raw or {}).get("game_id") or "")
        try:
            quote = validate_manual_quote(raw)
        except ManualQuoteError as exc:
            blocked.append({"row": index, "game_id": game_id, "reason": str(exc)})
            continue
        first_pitch_utc = _as_utc(quote.first_pitch_at)
        first_pitch_ct_date = first_pitch_utc.astimezone(CHICAGO_TZ).date().isoformat()
        if allowed and first_pitch_ct_date not in allowed:
            blocked.append({
                "row": index,
                "game_id": quote.game_id,
                "reason": f"MANUAL_INPUT_DATE_MISMATCH expected={run_date} first_pitch_date_ct={first_pitch_ct_date}",
            })
            continue
        if first_pitch_utc <= now:
            blocked.append({
                "row": index,
                "game_id": quote.game_id,
                "reason": f"MANUAL_QUOTE_GAME_STARTED game_id={quote.game_id}",
            })
            continue
        observed_utc = _as_utc(quote.observed_at)
        if (now - observed_utc).total_seconds() / 60.0 < 0:
            blocked.append({
                "row": index,
                "game_id": quote.game_id,
                "reason": f"MANUAL_QUOTE_FROM_FUTURE game_id={quote.game_id}",
            })
            continue
        live.append(raw)
    return live, blocked


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


def _run_canonical_rows(rows, *, history_cache_dir: str, schedule: list[GameSnapshot] | None = None) -> dict:
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(str(row.get("game_id")), []).append(row)
    if len(grouped) == 1:
        return run_canonical_manual_mlb(rows, history_cache_dir=history_cache_dir, schedule=schedule)
    games = []
    results = []
    for game_id, game_rows in grouped.items():
        payload = run_canonical_manual_mlb(game_rows, history_cache_dir=history_cache_dir, schedule=schedule)
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
    blocked: list[dict] = []
    if rows is not None and not args.allow_stale:
        as_of = parse_timestamp(args.as_of) if args.as_of else datetime.now(timezone.utc)
        rows, blocked = partition_live_rows(rows, run_date=args.run_date, max_age_minutes=args.max_age_minutes, as_of=as_of)

    schedule = _schedule_snapshot(snapshot)
    if rows:
        if isinstance(snapshot, dict):
            payload = _run_canonical_rows(rows, history_cache_dir=args.history_cache_dir, schedule=schedule)
        else:
            payload = _run_canonical_rows(rows, history_cache_dir=args.history_cache_dir, schedule=schedule)
    elif isinstance(snapshot, dict) and not rows:
        payload = {
            "schema_version": 2,
            "run_type": "CANONICAL_MANUAL_QUOTES_MULTI_GAME",
            "source": "MANUAL",
            "games": [],
            "results": [],
        }
    else:
        payload = run_manual_mlb_snapshot(snapshot, history_cache_dir=args.history_cache_dir)
    payload["blocked"] = blocked
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
