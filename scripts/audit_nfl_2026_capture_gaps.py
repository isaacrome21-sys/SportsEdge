#!/usr/bin/env python3
"""Audit NFL 2026 confirmation capture gaps without backfilling market data.

The audit has two jobs:
1. After a frozen OPENER or FINAL window has elapsed, write immutable
   MISSED_OR_BLOCKED evidence if the expected capture is absent.
2. During a live scheduled run, verify that every capture that was due actually
   materialized in repository data for that GitHub run.

FINAL expectations come only from the nflverse schedule snapshot already fetched
by the workflow. Matching is by kickoff timestamp multiplicity, not team-name or
provider IDs, so no cross-provider identifier guess is required.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def week_for_local_date(local_day: date, cfg: dict) -> int:
    anchor = date.fromisoformat(cfg["week1_tuesday_local_date"])
    return (local_day - anchor).days // 7 + 1


def week_for_tuesday(tuesday: date, cfg: dict) -> int:
    return week_for_local_date(tuesday, cfg)


def opener_window_for_week(week: int, cfg: dict):
    anchor = date.fromisoformat(cfg["week1_tuesday_local_date"])
    target_day = anchor + timedelta(days=7 * (week - 1))
    target_weekday = cfg["opener_weekday"]
    weekday_num = {"Sunday": 6, "Monday": 0, "Tuesday": 1}[target_weekday]
    target_day += timedelta(days=(weekday_num - target_day.weekday()) % 7)
    hh, mm = map(int, cfg["opener_local_time"].split(":"))
    tz = ZoneInfo(cfg["timezone"])
    start = datetime(target_day.year, target_day.month, target_day.day, hh, mm, tzinfo=tz)
    end = start + timedelta(minutes=int(cfg["opener_window_minutes"]))
    return start, end


def load_schedule(path: Path | None) -> tuple[list[dict], str | None]:
    if path is None:
        return [], None
    raw = path.read_bytes()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    return rows, hashlib.sha256(raw).hexdigest()


def schedule_kickoff_utc(row: dict) -> datetime | None:
    if str(row.get("season") or "") != "2026":
        return None
    gameday = str(row.get("gameday") or "").strip()
    gametime = str(row.get("gametime") or "").strip()
    if not gameday or not gametime:
        return None
    try:
        eastern = ZoneInfo("America/New_York")
        return datetime.fromisoformat(f"{gameday}T{gametime}").replace(tzinfo=eastern).astimezone(timezone.utc)
    except ValueError:
        return None


def captured_final_games(cfg: dict) -> list[dict]:
    games: list[dict] = []
    for path in Path(cfg["output_dir"]).glob("week*/final/*.json"):
        try:
            record = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        run_id = str((record.get("run") or {}).get("github_run_id") or "")
        for game in record.get("games") or []:
            games.append({"path": str(path), "run_id": run_id, **game})
    return games


def final_kickoff_counts(cfg: dict, *, github_run_id: str | None = None) -> Counter:
    counts: Counter = Counter()
    for game in captured_final_games(cfg):
        if github_run_id is not None and game.get("run_id") != str(github_run_id):
            continue
        commence = game.get("commence_time")
        if not commence:
            continue
        try:
            dt = datetime.fromisoformat(str(commence).replace("Z", "+00:00"))
        except ValueError:
            continue
        counts[iso_z(dt)] += 1
    return counts


def audit(cfg: dict, now: datetime, schedule_rows: list[dict] | None = None,
          schedule_sha256: str | None = None) -> list[Path]:
    out_dir = Path(cfg["output_dir"])
    tz = ZoneInfo(cfg["timezone"])
    local_now = now.astimezone(tz)
    anchor = date.fromisoformat(cfg["week1_tuesday_local_date"])
    current_week = max(1, (local_now.date() - anchor).days // 7 + 1)
    written: list[Path] = []

    # OPENER absence evidence.
    for week in range(int(cfg["first_week"]), current_week + 1):
        start, end = opener_window_for_week(week, cfg)
        if local_now < end:
            continue
        week_dir = out_dir / f"week{week:02d}"
        opener = week_dir / "opener.json"
        marker = week_dir / "opener_missed.json"
        if opener.exists() or marker.exists():
            continue
        week_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "status": "MISSED_OR_BLOCKED",
            "capture_kind": "OPENER",
            "week": week,
            "reason": "OPENER_WINDOW_ELAPSED_WITHOUT_CAPTURE",
            "target_local": start.isoformat(),
            "window_end_local": end.isoformat(),
            "observed_missing_at_utc": now.astimezone(timezone.utc).isoformat(),
            "expected_capture_path": str(opener),
            "no_backfill": True,
            "evidence_semantics": "ABSENCE_MARKER_ONLY_NOT_MARKET_DATA",
        }
        marker.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(marker)

    # FINAL absence evidence. Group by kickoff timestamp because nflverse IDs and
    # odds-provider event IDs are intentionally not assumed to be interchangeable.
    if schedule_rows:
        expected: Counter = Counter()
        for row in schedule_rows:
            kickoff = schedule_kickoff_utc(row)
            if kickoff is None:
                continue
            week = week_for_local_date(kickoff.astimezone(tz).date(), cfg)
            if week < int(cfg["first_week"]):
                continue
            lead = timedelta(minutes=int(cfg["final_minutes_before_kickoff"]))
            window = timedelta(minutes=int(cfg["final_window_minutes"]))
            window_end = min(kickoff - lead + window, kickoff)
            if now.astimezone(timezone.utc) >= window_end:
                expected[(week, iso_z(kickoff))] += 1

        captured = final_kickoff_counts(cfg)
        for (week, kickoff_z), expected_count in sorted(expected.items()):
            captured_count = captured[kickoff_z]
            if captured_count >= expected_count:
                continue
            stamp = kickoff_z.replace("-", "").replace(":", "")
            marker = out_dir / f"week{week:02d}" / "final_missed" / f"{stamp}.json"
            if marker.exists():
                continue
            marker.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "status": "MISSED_OR_BLOCKED",
                "capture_kind": "FINAL",
                "week": week,
                "reason": "FINAL_WINDOW_ELAPSED_WITH_INCOMPLETE_CAPTURE",
                "kickoff_utc": kickoff_z,
                "expected_games_at_kickoff": expected_count,
                "captured_games_at_kickoff": captured_count,
                "missing_games_at_kickoff": expected_count - captured_count,
                "observed_missing_at_utc": now.astimezone(timezone.utc).isoformat(),
                "schedule_source": "nflverse/nfldata data/games.csv",
                "schedule_sha256": schedule_sha256,
                "no_backfill": True,
                "evidence_semantics": "ABSENCE_MARKER_ONLY_NOT_MARKET_DATA",
            }
            marker.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            written.append(marker)
    return written


def verify_due(cfg: dict, opener_week: int | None, final_kickoffs: list[str],
               github_run_id: str) -> list[str]:
    failures: list[str] = []
    if opener_week is not None:
        opener = Path(cfg["output_dir"]) / f"week{opener_week:02d}" / "opener.json"
        if not opener.is_file():
            failures.append(f"DUE_OPENER_NOT_MATERIALIZED:{opener}")
        else:
            try:
                record = load_json(opener)
            except (OSError, json.JSONDecodeError):
                failures.append(f"DUE_OPENER_INVALID_JSON:{opener}")
            else:
                run_id = str((record.get("run") or {}).get("github_run_id") or "")
                if run_id != str(github_run_id):
                    failures.append(f"DUE_OPENER_NOT_FROM_CURRENT_RUN:{run_id or 'MISSING'}")
                if record.get("book") != cfg.get("bookmaker"):
                    failures.append("DUE_OPENER_WRONG_BOOK")
                if record.get("capture_kind") != "OPENER":
                    failures.append("DUE_OPENER_WRONG_KIND")
                if not record.get("retrieved_at_utc") or not record.get("hashes"):
                    failures.append("DUE_OPENER_MISSING_CONTRACT_FIELDS")
                if not isinstance(record.get("games"), list) or not record.get("games"):
                    failures.append("DUE_OPENER_EMPTY_OR_MISSING_GAMES")

    if final_kickoffs:
        expected = Counter(final_kickoffs)
        actual = final_kickoff_counts(cfg, github_run_id=github_run_id)
        for kickoff_z, expected_count in expected.items():
            if actual[kickoff_z] < expected_count:
                failures.append(
                    f"DUE_FINAL_NOT_MATERIALIZED:{kickoff_z}:expected={expected_count}:actual={actual[kickoff_z]}"
                )
        # Validate book/kind/contract fields for current-run FINAL records too.
        for path in Path(cfg["output_dir"]).glob("week*/final/*.json"):
            try:
                record = load_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            if str((record.get("run") or {}).get("github_run_id") or "") != str(github_run_id):
                continue
            if record.get("book") != cfg.get("bookmaker"):
                failures.append(f"DUE_FINAL_WRONG_BOOK:{path}")
            if record.get("capture_kind") != "FINAL":
                failures.append(f"DUE_FINAL_WRONG_KIND:{path}")
            if not record.get("retrieved_at_utc") or not record.get("hashes"):
                failures.append(f"DUE_FINAL_MISSING_CONTRACT_FIELDS:{path}")
            if not isinstance(record.get("games"), list) or not record.get("games"):
                failures.append(f"DUE_FINAL_EMPTY_OR_MISSING_GAMES:{path}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/nfl_2026_capture.json")
    parser.add_argument("--now", help="ISO timestamp override for deterministic tests/audits")
    parser.add_argument("--schedule-csv", help="nflverse games.csv snapshot used by this run")
    parser.add_argument("--verify-opener-week", type=int)
    parser.add_argument("--verify-final-kickoffs", default="[]", help="JSON list of due kickoff UTC timestamps")
    parser.add_argument("--github-run-id")
    args = parser.parse_args()

    cfg = load_json(Path(args.config))
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise SystemExit("NFL_CAPTURE_GAP_AUDIT_NOW_MUST_BE_TIMEZONE_AWARE")
    schedule_rows, schedule_sha = load_schedule(Path(args.schedule_csv) if args.schedule_csv else None)
    written = audit(cfg, now, schedule_rows, schedule_sha)

    try:
        final_kickoffs = json.loads(args.verify_final_kickoffs)
    except json.JSONDecodeError:
        print(json.dumps({"status": "FAIL", "failures": ["INVALID_VERIFY_FINAL_KICKOFFS_JSON"]}, sort_keys=True))
        return 1
    if not isinstance(final_kickoffs, list):
        print(json.dumps({"status": "FAIL", "failures": ["VERIFY_FINAL_KICKOFFS_NOT_LIST"]}, sort_keys=True))
        return 1

    failures: list[str] = []
    verification_requested = args.verify_opener_week is not None or bool(final_kickoffs)
    if verification_requested:
        if not args.github_run_id:
            failures.append("VERIFY_GITHUB_RUN_ID_REQUIRED")
        else:
            failures.extend(verify_due(cfg, args.verify_opener_week, final_kickoffs, args.github_run_id))

    status = "PASS" if not failures else "FAIL"
    print(json.dumps({
        "status": status,
        "markers_written": [str(p) for p in written],
        "failures": failures,
    }, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())