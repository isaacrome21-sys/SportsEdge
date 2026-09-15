#!/usr/bin/env python3
"""Fail-closed guards for preregistered evidence windows.

Two independent failure modes are covered:

* mutation: an ACTIVE window loses or weakens its declared acquisition authority
  without first receiving an explicit registry disposition;
* nfl-liveness: a frozen NFL confirmation capture window elapsed recently but no
  contract-valid durable capture exists.

A green GitHub Actions run is never accepted as evidence of liveness.  The NFL
check reads only the durable capture records in the checkout plus the frozen
schedule snapshot supplied by the caller.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"ACTIVE_WINDOW_JSON_INVALID:{path}") from exc


def _aware(value: str | None) -> datetime:
    if value:
        try:
            out = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SystemExit("ACTIVE_WINDOW_NOW_INVALID") from exc
    else:
        out = datetime.now(timezone.utc)
    if out.tzinfo is None or out.utcoffset() is None:
        raise SystemExit("ACTIVE_WINDOW_NOW_MUST_BE_TIMEZONE_AWARE")
    return out.astimezone(timezone.utc)


def mutation_failures(repo_root: Path, registry_path: Path) -> list[str]:
    registry = _json(registry_path)
    if not isinstance(registry, dict) or registry.get("schema") != "SPORTSEDGE_ACTIVE_EVIDENCE_WINDOWS_V1":
        return ["ACTIVE_WINDOW_REGISTRY_SCHEMA_INVALID"]
    windows = registry.get("windows")
    if not isinstance(windows, list) or not windows:
        return ["ACTIVE_WINDOW_REGISTRY_EMPTY"]

    failures: list[str] = []
    ids: set[str] = set()
    for raw in windows:
        if not isinstance(raw, dict):
            failures.append("ACTIVE_WINDOW_ENTRY_NOT_OBJECT")
            continue
        window_id = str(raw.get("id") or "").strip()
        if not window_id:
            failures.append("ACTIVE_WINDOW_ID_MISSING")
            continue
        if window_id in ids:
            failures.append(f"ACTIVE_WINDOW_ID_DUPLICATE:{window_id}")
            continue
        ids.add(window_id)
        if raw.get("status") != "ACTIVE":
            continue

        authority = str(raw.get("acquisition_authority") or "").strip()
        if not authority:
            failures.append(f"ACTIVE_WINDOW_AUTHORITY_MISSING:{window_id}")
            continue
        authority_path = repo_root / authority
        if not authority_path.is_file():
            failures.append(f"ACTIVE_WINDOW_AUTHORITY_NOT_FOUND:{window_id}:{authority}")
            continue
        text = authority_path.read_text(encoding="utf-8")
        for literal in raw.get("required_authority_literals") or []:
            literal = str(literal)
            if literal not in text:
                failures.append(f"ACTIVE_WINDOW_AUTHORITY_CONTRACT_MISSING:{window_id}:{literal}")

        persistence_root = str(raw.get("persistence_root") or "").strip()
        if persistence_root and persistence_root not in text:
            failures.append(f"ACTIVE_WINDOW_PERSISTENCE_CONTRACT_MISSING:{window_id}:{persistence_root}")

        liveness_authority = str(raw.get("independent_liveness_authority") or "").strip()
        if liveness_authority:
            liveness_path = repo_root / liveness_authority
            if not liveness_path.is_file():
                failures.append(f"ACTIVE_WINDOW_LIVENESS_AUTHORITY_NOT_FOUND:{window_id}:{liveness_authority}")
            else:
                liveness_text = liveness_path.read_text(encoding="utf-8")
                required = raw.get("required_liveness_literals") or ["check_active_evidence_windows.py"]
                for literal in required:
                    literal = str(literal)
                    if literal not in liveness_text:
                        failures.append(f"ACTIVE_WINDOW_LIVENESS_CONTRACT_MISSING:{window_id}:{literal}")
    return failures


def _valid_capture(record: Any, cfg: dict[str, Any], kind: str) -> bool:
    if not isinstance(record, dict):
        return False
    if record.get("capture_kind") != kind or record.get("book") != cfg.get("bookmaker"):
        return False
    if not record.get("retrieved_at_utc"):
        return False
    hashes = record.get("hashes")
    games = record.get("games")
    return isinstance(hashes, dict) and bool(hashes) and isinstance(games, list) and bool(games)


def _week(local_day: date, cfg: dict[str, Any]) -> int:
    anchor = date.fromisoformat(str(cfg["week1_tuesday_local_date"]))
    return (local_day - anchor).days // 7 + 1


def _opener_window(week: int, cfg: dict[str, Any]) -> tuple[datetime, datetime]:
    anchor = date.fromisoformat(str(cfg["week1_tuesday_local_date"]))
    target_day = anchor + timedelta(days=7 * (week - 1))
    weekday = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
               "Friday": 4, "Saturday": 5, "Sunday": 6}[str(cfg["opener_weekday"])]
    target_day += timedelta(days=(weekday - target_day.weekday()) % 7)
    hour, minute = map(int, str(cfg["opener_local_time"]).split(":"))
    tz = ZoneInfo(str(cfg["timezone"]))
    start = datetime(target_day.year, target_day.month, target_day.day, hour, minute, tzinfo=tz)
    return start, start + timedelta(minutes=int(cfg["opener_window_minutes"]))


def _schedule_kickoff(row: dict[str, str]) -> datetime | None:
    if str(row.get("season") or "") != "2026":
        return None
    day = str(row.get("gameday") or "").strip()
    clock = str(row.get("gametime") or "").strip()
    if not day or not clock:
        return None
    try:
        local = datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=ZoneInfo("America/New_York"))
    except ValueError:
        return None
    return local.astimezone(timezone.utc)


def _captured_final_counts(cfg: dict[str, Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    root = Path(str(cfg["output_dir"]))
    for path in root.glob("week*/final/*.json"):
        try:
            record = _json(path)
        except SystemExit:
            continue
        if not _valid_capture(record, cfg, "FINAL"):
            continue
        for game in record.get("games") or []:
            raw = str(game.get("commence_time") or "").strip()
            if not raw:
                continue
            try:
                kickoff = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
            except ValueError:
                continue
            counts[kickoff.strftime("%Y-%m-%dT%H:%M:%SZ")] += 1
    return counts


def nfl_liveness_failures(cfg_path: Path, schedule_path: Path, now: datetime,
                          lookback_hours: float) -> list[str]:
    cfg = _json(cfg_path)
    if not isinstance(cfg, dict):
        return ["NFL_LIVENESS_CONFIG_NOT_OBJECT"]
    tz = ZoneInfo(str(cfg["timezone"]))
    local_now = now.astimezone(tz)
    lookback = timedelta(hours=float(lookback_hours))
    failures: list[str] = []
    output_root = Path(str(cfg["output_dir"]))

    current_week = max(int(cfg["first_week"]), _week(local_now.date(), cfg))
    for week in range(int(cfg["first_week"]), current_week + 1):
        _, end = _opener_window(week, cfg)
        elapsed = local_now - end
        if elapsed < timedelta(0) or elapsed > lookback:
            continue
        opener = output_root / f"week{week:02d}" / "opener.json"
        valid = False
        if opener.is_file():
            try:
                valid = _valid_capture(_json(opener), cfg, "OPENER")
            except SystemExit:
                valid = False
        if not valid:
            marker = output_root / f"week{week:02d}" / "opener_missed.json"
            suffix = ":TERMINAL_MARKER_PRESENT" if marker.is_file() else ":NO_TERMINAL_RECORD"
            failures.append(f"NFL_ACTIVE_WINDOW_ZERO_VALID_OPENER:week={week}{suffix}")

    expected: Counter[str] = Counter()
    with schedule_path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        kickoff = _schedule_kickoff(row)
        if kickoff is None:
            continue
        week = _week(kickoff.astimezone(tz).date(), cfg)
        if week < int(cfg["first_week"]):
            continue
        start = kickoff - timedelta(minutes=int(cfg["final_minutes_before_kickoff"]))
        end = min(start + timedelta(minutes=int(cfg["final_window_minutes"])), kickoff)
        elapsed = now - end
        if elapsed < timedelta(0) or elapsed > lookback:
            continue
        expected[kickoff.strftime("%Y-%m-%dT%H:%M:%SZ")] += 1

    actual = _captured_final_counts(cfg)
    for kickoff_z, count in sorted(expected.items()):
        if actual[kickoff_z] < count:
            failures.append(
                f"NFL_ACTIVE_WINDOW_ZERO_OR_INCOMPLETE_FINAL:{kickoff_z}:expected={count}:actual={actual[kickoff_z]}"
            )
    return failures


def _emit(mode: str, failures: list[str]) -> int:
    status = "PASS" if not failures else "FAIL"
    print(json.dumps({"mode": mode, "status": status, "failures": failures}, sort_keys=True))
    return 0 if not failures else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    mutation = sub.add_parser("mutation")
    mutation.add_argument("--registry", type=Path, default=Path("config/active_evidence_windows_v1.json"))
    mutation.add_argument("--repo-root", type=Path, default=Path("."))

    live = sub.add_parser("nfl-liveness")
    live.add_argument("--capture-config", type=Path, default=Path("config/nfl_2026_capture.json"))
    live.add_argument("--schedule-csv", type=Path, required=True)
    live.add_argument("--now")
    live.add_argument("--lookback-hours", type=float, default=4.0)

    args = parser.parse_args()
    if args.command == "mutation":
        return _emit("mutation", mutation_failures(args.repo_root, args.registry))
    return _emit(
        "nfl-liveness",
        nfl_liveness_failures(args.capture_config, args.schedule_csv, _aware(args.now), args.lookback_hours),
    )


if __name__ == "__main__":
    raise SystemExit(main())
