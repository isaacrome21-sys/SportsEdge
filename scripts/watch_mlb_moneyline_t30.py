#!/usr/bin/env python3
"""Keep a live, zero-stake MLB moneyline decision watch through frozen T30.

GitHub Actions schedules are best-effort. A T60 prediction must not depend on
another cron firing during the narrow T36--T30 freeze interval. This process
waits on the *runner's clock*, fetches a new paired DraftKings quote, and calls
the existing governed decision writer. It cannot backdate, loosen the lane,
promote a market, or turn PAPER evidence into a PLAY.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable, Mapping

from scripts.capture_mlb_direct_paired_ml import capture as capture_quotes
from scripts.capture_mlb_moneyline_paper_decisions import capture_decisions

TARGET_MINUTES = 30
START_WATCH_MINUTES = 35
MAX_LOOKAHEAD_MINUTES = 60
RETRY_SECONDS = 20
VALID_TERMINALS = {"PAPER_BET_FROZEN", "PAPER_PASS_FROZEN"}
DEFAULT_PREDICTIONS = "data/mlb_forward_predictions"
DEFAULT_QUOTES = "data/mlb_forward_capture"
DEFAULT_DECISIONS = "data/mlb_forward_decisions"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("watch clock must be timezone-aware")
    return value.astimezone(timezone.utc)


def _load(root: str | Path) -> list[dict[str, Any]]:
    directory = Path(root)
    if not directory.exists():
        return []
    rows = []
    for path in sorted(directory.rglob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(row, dict):
            raise ValueError(f"expected JSON object: {path}")
        rows.append(row)
    return rows


def _existing(root: str | Path) -> dict[int, Mapping[str, Any]]:
    out: dict[int, Mapping[str, Any]] = {}
    for row in _load(root):
        game = int(row["game_pk"])
        if game in out:
            raise ValueError(f"duplicate immutable decision: {game}")
        out[game] = row
    return out


def _watchable(predictions: list[Mapping[str, Any]], decisions: Mapping[int, Any], now: datetime) -> dict[int, datetime]:
    games: dict[int, datetime] = {}
    for row in predictions:
        game = int(row["game_pk"])
        if game in decisions:
            continue
        if row.get("market") != "MONEYLINE" or row.get("market_blind") is not True:
            raise ValueError(f"not a market-blind moneyline prediction: {game}")
        start = _utc(datetime.fromisoformat(str(row["event_start_ts"]).replace("Z", "+00:00")))
        minutes = (start - now).total_seconds() / 60
        if TARGET_MINUTES <= minutes <= MAX_LOOKAHEAD_MINUTES:
            if game in games and games[game] != start:
                raise ValueError(f"conflicting game start for {game}")
            games[game] = start
    return games


def watch_t30(
    *,
    prediction_root: str | Path = DEFAULT_PREDICTIONS,
    quote_root: str | Path = DEFAULT_QUOTES,
    decision_root: str | Path = DEFAULT_DECISIONS,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sleeper: Callable[[float], None] = time.sleep,
    quote_capture: Callable[..., Any] = capture_quotes,
    decision_capture: Callable[..., Any] = capture_decisions,
) -> dict[str, Any]:
    now = _utc(clock())
    existing = _existing(decision_root)
    watch = _watchable(_load(prediction_root), existing, now)
    if not watch:
        return {"status": "NO_T30_WATCH_DUE", "watched": 0, "valid_frozen": [], "missed": [], "promotion_authority": False}

    completed: list[int] = []
    missed: list[int] = []
    attempts: dict[int, int] = {game: 0 for game in watch}
    errors: dict[int, str] = {}
    while watch:
        now = _utc(clock())
        due = [g for g, start in watch.items() if start - timedelta(minutes=START_WATCH_MINUTES) <= now <= start - timedelta(minutes=TARGET_MINUTES)]
        if due:
            for game in due:
                attempts[game] += 1
            try:
                quote_capture(output_dir=quote_root)
                decision_capture(prediction_root=prediction_root, quote_root=quote_root, decision_root=decision_root)
            except Exception as exc:
                for game in due:
                    errors[game] = f"{type(exc).__name__}: {exc}"
            terminal = _existing(decision_root)
            for game in due:
                status = str(terminal.get(game, {}).get("status") or "")
                if status in VALID_TERMINALS:
                    completed.append(game)
                    watch.pop(game)
                elif status == "BLOCKED_MISSED_DECISION_FREEZE":
                    missed.append(game)
                    watch.pop(game)

        now = _utc(clock())
        for game, start in list(watch.items()):
            if now >= start - timedelta(minutes=TARGET_MINUTES):
                missed.append(game)
                watch.pop(game)
        if not watch:
            break
        next_attempt = min(
            max(0.0, (start - timedelta(minutes=START_WATCH_MINUTES) - now).total_seconds())
            if now < start - timedelta(minutes=START_WATCH_MINUTES)
            else RETRY_SECONDS
            for start in watch.values()
        )
        next_deadline = min((start - timedelta(minutes=TARGET_MINUTES) - now).total_seconds() for start in watch.values())
        # A short heartbeat also makes clock drift/cancel signals observable;
        # waiting for a prospective window never depends on another cron run.
        sleeper(max(0.01, min(next_attempt, next_deadline, 30.0)))

    return {
        "status": "T30_WATCH_COMPLETE" if not missed else "T30_WATCH_MISSED",
        "watched": len(attempts),
        "valid_frozen": sorted(completed),
        "missed": sorted(set(missed)),
        "attempts": attempts,
        "last_errors": errors,
        "promotion_authority": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prediction-root", default=DEFAULT_PREDICTIONS)
    parser.add_argument("--quote-root", default=DEFAULT_QUOTES)
    parser.add_argument("--decision-root", default=DEFAULT_DECISIONS)
    args = parser.parse_args(argv)
    try:
        result = watch_t30(prediction_root=args.prediction_root, quote_root=args.quote_root, decision_root=args.decision_root)
    except Exception as exc:
        print(json.dumps({"status": "T30_WATCH_ERROR", "reason": str(exc), "promotion_authority": False}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] != "T30_WATCH_MISSED" else 2


if __name__ == "__main__":
    sys.exit(main())
