#!/usr/bin/env python3
"""Owner-requested CFB evidence jobs. No pricing or promotion decisions."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.capture_cfb_final_scores import ESPN, SCHEMA
from scripts.cfb_probation_ledger import _norm, _utc


def due_starts(payload, now):
    """Next ten minutes, excluding started games. Delayed jobs never backfill."""
    starts = set()
    for event in payload.get("events") or []:
        status = (event.get("status") or {}).get("type") or {}
        if status.get("state") != "pre":
            continue
        start = _utc(event["date"])
        if now < start <= now + timedelta(minutes=10):
            starts.add(start)
    return sorted(starts)


def eligible_close_rows(board, *, now, target_starts):
    out = []
    for game in board:
        start = _utc(game["start_ts"])
        if start not in target_starts or now >= start:
            continue
        stamps = game.get("quote_observed_at_by_market") or {}
        if not stamps or any(not 0 <= (now - _utc(t)).total_seconds() <= 180 for t in stamps.values()):
            continue
        out.append(dict(game, recorded_at_utc=now.isoformat()))
    return out


def select_closes(ledger, paths):
    """Last saved pre-start board for the exact teams and kickoff, never postgame."""
    all_rows = []
    for path in paths:
        all_rows.extend(json.loads(path.read_text()))
    selected = {}
    for play in ledger["plays"]:
        key = (_norm(play["away"]), _norm(play["home"]), _utc(play["start_ts"]))
        matches = []
        for row in all_rows:
            if (_norm(row["away"]), _norm(row["home"]), _utc(row["start_ts"])) != key:
                continue
            stamp = _utc(row["recorded_at_utc"])
            quote_times = row.get("quote_observed_at_by_market") or {}
            if stamp < key[2] and quote_times and all(_utc(t) <= stamp for t in quote_times.values()):
                matches.append(row)
        if matches:
            last = max(_utc(r["recorded_at_utc"]) for r in matches)
            candidates = [r for r in matches if _utc(r["recorded_at_utc"]) == last]
            if len({json.dumps(r, sort_keys=True) for r in candidates}) != 1:
                raise ValueError("CFB_CLOSE_AMBIGUOUS")
            selected[key] = candidates[0]
    return list(selected.values())


def close_job(output):
    from scripts.collect_auto_dk_four_sports import collect, DEFAULT_RESERVE
    now = datetime.now(timezone.utc)
    day = now.astimezone(ZoneInfo("America/Chicago")).date()
    req = Request(ESPN.format(d=day.strftime("%Y%m%d")), headers={"User-Agent": "SportsEdge/1.0"})
    with urlopen(req, timeout=45) as response:
        starts = due_starts(json.load(response), now)
    saved = set()
    for path in output.rglob("close_board.json"):
        for row in json.loads(path.read_text()):
            if _utc(row["recorded_at_utc"]) < _utc(row["start_ts"]):
                saved.add(_utc(row["start_ts"]))
    starts = [start for start in starts if start not in saved]
    if not starts:
        print("NO_UPCOMING_CFB_KICKOFF")
        return
    # Target five minutes before the earliest kickoff; one poll covers its group.
    target = starts[0] - timedelta(minutes=5)
    while datetime.now(timezone.utc) < target:
        time.sleep(max(0, min(30, (target - datetime.now(timezone.utc)).total_seconds())))
    captured = datetime.now(timezone.utc)
    directory = output / captured.strftime("%Y%m%dT%H%M%S%fZ")
    if directory.exists():
        raise ValueError("CFB_CLOSE_IMMUTABLE_PATH_EXISTS")
    collect(["CFB"], directory, captured, DEFAULT_RESERVE)
    completed = datetime.now(timezone.utc)
    board = json.loads((directory / "cfb_dk_board.json").read_text())
    rows = eligible_close_rows(board, now=completed, target_starts=set(starts))
    (directory / "close_board.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(f"CFB_CLOSE_SAVED games={len(rows)} target={target.isoformat()} actual={completed.isoformat()}")


def weekend_job(output, *, now=None):
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(ZoneInfo("America/Chicago")).date()
    # Last completed Saturday + preceding Friday, including Sunday invocation.
    saturday = day - timedelta(days=(day.weekday() - 5) % 7 or 7)
    dates = [saturday - timedelta(days=1), saturday]
    finals = []
    for date in dates:
        subprocess.run([sys.executable, "scripts/capture_cfb_final_scores.py", "capture",
                        "--date", date.isoformat(), "--output-dir", "ledger/cfb_finals"], check=True)
        finals.extend(json.loads(Path(f"ledger/cfb_finals/{date}.json").read_text())["games"])
    output.mkdir(parents=True, exist_ok=False)
    combined = output / "finals.json"
    combined.write_text(json.dumps({"schema": SCHEMA, "games": finals}, indent=2) + "\n")
    paths = sorted(Path("ledger/cfb_closes").rglob("close_board.json"))
    for ledger in sorted(Path("ledger/cfb_probation").glob("*.json")):
        data = json.loads(ledger.read_text())
        if not any(_utc(p["start_ts"]).astimezone(ZoneInfo("America/Chicago")).date() in dates for p in data["plays"]):
            continue
        close_file = output / (ledger.stem + "-close_board.json")
        close_file.write_text(json.dumps(select_closes(data, paths), indent=2) + "\n")
        subprocess.run([sys.executable, "scripts/capture_cfb_final_scores.py", "grade", "--ledger", str(ledger),
                        "--finals", str(combined), "--closing", str(close_file),
                        "--output", str(output / ledger.name)], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["close", "weekend"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "close":
        close_job(args.output)
    else:
        weekend_job(args.output)


if __name__ == "__main__":
    main()
