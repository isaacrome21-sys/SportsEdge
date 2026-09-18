#!/usr/bin/env python3
"""Fail-closed guards for preregistered evidence windows.

Independent failure modes are covered:

* mutation: an ACTIVE window loses or weakens its declared acquisition authority
  without first receiving an explicit registry disposition;
* nfl-liveness: a frozen NFL confirmation capture window elapsed recently but no
  contract-valid durable capture exists;
* mlb-moneyline-liveness: a frozen MLB MONEYLINE T30 decision window elapsed
  recently but no contract-valid durable PAPER terminal exists.

A green GitHub Actions run is never accepted as evidence of liveness. These
checks read durable data-branch records plus public schedule snapshots supplied
by the caller. A missed MLB decision remains a failure; it is never backfilled or
reclassified merely because the runner itself was green.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any, Mapping
from zoneinfo import ZoneInfo

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MLB_VALID_DECISION_STATUSES = {"PAPER_BET_FROZEN", "PAPER_PASS_FROZEN"}
MLB_BLOCKED_DECISION_STATUSES = {"BLOCKED_MISSED_DECISION_FREEZE", "BLOCKED_MISSED_DECISION_WINDOW"}


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


def _timestamp(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        out = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if out.tzinfo is None or out.utcoffset() is None:
        return None
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


def _mlb_schedule_games(schedule_path: Path) -> list[tuple[int, datetime]]:
    payload = _json(schedule_path)
    if not isinstance(payload, Mapping):
        raise SystemExit("MLB_MONEYLINE_LIVENESS_SCHEDULE_NOT_OBJECT")
    games: list[tuple[int, datetime]] = []
    seen: set[int] = set()
    for day in payload.get("dates") or []:
        if not isinstance(day, Mapping):
            continue
        for game in day.get("games") or []:
            if not isinstance(game, Mapping):
                continue
            status = game.get("status") or {}
            detailed = str(status.get("detailedState") or "").strip().lower()
            if detailed in {"postponed", "cancelled", "canceled"}:
                continue
            try:
                game_pk = int(game.get("gamePk"))
            except (TypeError, ValueError):
                continue
            start = _timestamp(game.get("gameDate"))
            if start is None:
                continue
            if game_pk in seen:
                raise SystemExit(f"MLB_MONEYLINE_LIVENESS_DUPLICATE_SCHEDULE_GAME:{game_pk}")
            seen.add(game_pk)
            games.append((game_pk, start))
    return games


def _mlb_decision_rows(root: Path) -> dict[int, list[dict[str, Any]]]:
    rows: dict[int, list[dict[str, Any]]] = {}
    if not root.exists():
        return rows
    for path in sorted(root.rglob("*.json")):
        try:
            record = _json(path)
        except SystemExit:
            continue
        if not isinstance(record, dict):
            continue
        try:
            game_pk = int(record.get("game_pk"))
        except (TypeError, ValueError):
            continue
        rows.setdefault(game_pk, []).append(record)
    return rows


def _valid_mlb_moneyline_terminal(record: Mapping[str, Any], game_pk: int,
                                  event_start: datetime) -> bool:
    status = str(record.get("status") or "")
    if status not in MLB_VALID_DECISION_STATUSES:
        return False
    try:
        if int(record.get("game_pk")) != game_pk:
            return False
    except (TypeError, ValueError):
        return False
    if str(record.get("lane_id") or "") != "MLB_MONEYLINE_DK_T30_V1":
        return False
    if str(record.get("state") or "") != "PAPER" or float(record.get("stake_units", -1)) != 0.0:
        return False
    if record.get("promotion_authority") is not False:
        return False
    for field in (
        "lane_definition_sha256",
        "market_definition_sha256",
        "policy_sha256",
        "policy_manifest_sha256",
        "edge_floor_config_sha256",
        "model_artifact_sha256",
        "prediction_record_sha256",
    ):
        if SHA256_RE.fullmatch(str(record.get(field) or "")) is None:
            return False
    start = _timestamp(record.get("event_start_ts"))
    frozen = _timestamp(record.get("decision_frozen_at_utc"))
    quote = _timestamp(record.get("decision_quote_observed_at_utc"))
    if start is None or frozen is None or quote is None:
        return False
    if abs((start - event_start).total_seconds()) > 1.0:
        return False
    freeze_minutes = (start - frozen).total_seconds() / 60.0
    quote_minutes = (start - quote).total_seconds() / 60.0
    if not (30.0 <= freeze_minutes <= 36.0 and 30.0 <= quote_minutes <= 36.0 and quote <= frozen < start):
        return False
    if status == "PAPER_BET_FROZEN":
        return record.get("graded_bet") is True and record.get("evidence_counts") is True
    return record.get("graded_bet") is False and record.get("evidence_counts") is False


def mlb_moneyline_liveness_failures(schedule_path: Path, decision_root: Path,
                                    now: datetime, lookback_hours: float) -> list[str]:
    """Return failures for recently elapsed frozen T30 windows without durable valid terminals.

    Only the recent operational lookback is evaluated. Historical misses remain
    immutable on the data branch and are not reclassified, but they do not make
    this operational deadman permanently red after the lookback expires.
    """
    games = _mlb_schedule_games(schedule_path)
    rows_by_game = _mlb_decision_rows(decision_root)
    lookback = timedelta(hours=float(lookback_hours))
    failures: list[str] = []
    for game_pk, start in games:
        decision_window_end = start - timedelta(minutes=30)
        elapsed = now - decision_window_end
        if elapsed < timedelta(0) or elapsed > lookback:
            continue
        candidates = rows_by_game.get(game_pk, [])
        valid = [row for row in candidates if _valid_mlb_moneyline_terminal(row, game_pk, start)]
        if len(valid) == 1:
            continue
        blocked = sorted({
            str(row.get("status") or "") for row in candidates
            if str(row.get("status") or "") in MLB_BLOCKED_DECISION_STATUSES
        })
        if len(valid) > 1:
            failures.append(f"MLB_MONEYLINE_ACTIVE_WINDOW_DUPLICATE_VALID_TERMINAL:game={game_pk}:valid={len(valid)}")
        elif blocked:
            failures.append(
                f"MLB_MONEYLINE_ACTIVE_WINDOW_NONACCRUAL:game={game_pk}:terminal={'+'.join(blocked)}"
            )
        else:
            failures.append(f"MLB_MONEYLINE_ACTIVE_WINDOW_ZERO_VALID_TERMINAL:game={game_pk}")
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

    mlb = sub.add_parser("mlb-moneyline-liveness")
    mlb.add_argument("--schedule-json", type=Path, required=True)
    mlb.add_argument("--decision-root", type=Path, required=True)
    mlb.add_argument("--now")
    mlb.add_argument("--lookback-hours", type=float, default=4.0)

    args = parser.parse_args()
    if args.command == "mutation":
        return _emit("mutation", mutation_failures(args.repo_root, args.registry))
    if args.command == "nfl-liveness":
        return _emit(
            "nfl-liveness",
            nfl_liveness_failures(args.capture_config, args.schedule_csv, _aware(args.now), args.lookback_hours),
        )
    return _emit(
        "mlb-moneyline-liveness",
        mlb_moneyline_liveness_failures(
            args.schedule_json,
            args.decision_root,
            _aware(args.now),
            args.lookback_hours,
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
