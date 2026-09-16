"""Schedule-completeness guard for the NFL 2026 confirmation lane.

The nflverse schedule snapshot is identity-independent evidence of which kickoffs
must be represented by an OPENER or a live FINAL capture. Matching uses kickoff
UTC timestamp multiplicity, not team names or provider event IDs.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

SCHEDULE_ENV = "NFL_SCHEDULE_CSV"
SCHEDULE_SOURCE = "nflverse/nfldata data/games.csv"
SEASON = 2026


class ScheduleExpectationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScheduleSnapshot:
    path: str
    sha256: str
    rows: tuple[dict[str, str], ...]

    def provenance(self) -> dict[str, object]:
        return {
            "source": SCHEDULE_SOURCE,
            "sha256": self.sha256,
            "matching_semantics": "KICKOFF_UTC_MULTIPLICITY",
        }


def iso_z(dt: datetime) -> str:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ScheduleExpectationError("SCHEDULE_TIME_NAIVE")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_snapshot(path: str | Path | None = None) -> ScheduleSnapshot:
    raw_path = str(path or os.environ.get(SCHEDULE_ENV, "")).strip()
    if not raw_path:
        raise ScheduleExpectationError("NFL_SCHEDULE_SNAPSHOT_REQUIRED")
    target = Path(raw_path)
    if not target.is_file():
        raise ScheduleExpectationError("NFL_SCHEDULE_SNAPSHOT_MISSING")
    raw = target.read_bytes()
    try:
        with target.open(newline="", encoding="utf-8-sig") as handle:
            rows = tuple(dict(r) for r in csv.DictReader(handle))
    except Exception as exc:
        raise ScheduleExpectationError("NFL_SCHEDULE_SNAPSHOT_PARSE_FAILED") from exc
    if not rows:
        raise ScheduleExpectationError("NFL_SCHEDULE_SNAPSHOT_EMPTY")
    return ScheduleSnapshot(str(target), hashlib.sha256(raw).hexdigest(), rows)


def schedule_kickoff_utc(row: Mapping[str, str]) -> datetime | None:
    if str(row.get("season") or "") != str(SEASON):
        return None
    gameday = str(row.get("gameday") or "").strip()
    gametime = str(row.get("gametime") or "").strip()
    if not gameday or not gametime:
        return None
    try:
        eastern = ZoneInfo("America/New_York")
        return datetime.fromisoformat(f"{gameday}T{gametime}").replace(
            tzinfo=eastern
        ).astimezone(timezone.utc)
    except ValueError:
        return None


def week_of(kickoff: datetime, cfg: Mapping[str, object]) -> int:
    tz = ZoneInfo(str(cfg["timezone"]))
    local_day = kickoff.astimezone(tz).date()
    anchor = date.fromisoformat(str(cfg["week1_tuesday_local_date"]))
    return (local_day - anchor).days // 7 + 1


def opener_expected_kickoffs(
    cfg: Mapping[str, object], week: int, snapshot: ScheduleSnapshot
) -> Counter[str]:
    expected: Counter[str] = Counter()
    for row in snapshot.rows:
        kickoff = schedule_kickoff_utc(row)
        if kickoff is None:
            continue
        if week_of(kickoff, cfg) == int(week):
            expected[iso_z(kickoff)] += 1
    if not expected:
        raise ScheduleExpectationError(f"NFL_OPENER_SCHEDULE_EMPTY:week={week}")
    return expected


def _record_admissible(record: Mapping[str, object], cfg: Mapping[str, object]) -> bool:
    if record.get("capture_kind") != "FINAL":
        return False
    if record.get("book") != cfg.get("bookmaker"):
        return False
    if record.get("source_class") not in (cfg.get("source_priority") or []):
        return False
    if not record.get("retrieved_at_utc"):
        return False
    hashes = record.get("hashes")
    if not isinstance(hashes, Mapping) or not hashes:
        return False
    if cfg.get("schedule_coverage_semantics"):
        schedule = record.get("schedule")
        if not isinstance(schedule, Mapping):
            return False
        if schedule.get("matching_semantics") != "KICKOFF_UTC_MULTIPLICITY":
            return False
        if not schedule.get("sha256"):
            return False
    games = record.get("games")
    if not isinstance(games, list) or not games:
        return False
    for game in games:
        if not isinstance(game, Mapping):
            return False
        spread = game.get("spread")
        total = game.get("total")
        if not isinstance(spread, Mapping) or spread.get("status") != "OK":
            return False
        if not isinstance(total, Mapping) or total.get("status") != "OK":
            return False
    return True


def _admissible_final_records(cfg: Mapping[str, object]):
    root = Path(str(cfg["output_dir"]))
    for path in root.glob("week*/final/*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, Mapping) and _record_admissible(record, cfg):
            yield record


def captured_final_kickoffs(cfg: Mapping[str, object]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for record in _admissible_final_records(cfg):
        for game in record.get("games") or []:
            raw = str(game.get("commence_time") or "").strip()
            if not raw:
                continue
            try:
                kickoff = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            counts[iso_z(kickoff)] += 1
    return counts


def captured_final_event_ids(cfg: Mapping[str, object]) -> set[str]:
    ids: set[str] = set()
    for record in _admissible_final_records(cfg):
        for game in record.get("games") or []:
            event_id = str(game.get("event_id") or "").strip()
            if event_id:
                ids.add(event_id)
    return ids


def final_expected_due_kickoffs(
    cfg: Mapping[str, object], now: datetime, snapshot: ScheduleSnapshot
) -> Counter[str]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ScheduleExpectationError("NFL_FINAL_NOW_NAIVE")
    now_utc = now.astimezone(timezone.utc)
    lead = timedelta(minutes=int(cfg["final_minutes_before_kickoff"]))
    width = timedelta(minutes=int(cfg["final_window_minutes"]))
    expected: Counter[str] = Counter()
    for row in snapshot.rows:
        kickoff = schedule_kickoff_utc(row)
        if kickoff is None or week_of(kickoff, cfg) < int(cfg["first_week"]):
            continue
        start = kickoff - lead
        end = min(start + width, kickoff)
        if start <= now_utc < end:
            expected[iso_z(kickoff)] += 1

    captured = captured_final_kickoffs(cfg)
    outstanding: Counter[str] = Counter()
    for kickoff_z, count in expected.items():
        missing = max(0, count - captured[kickoff_z])
        if missing:
            outstanding[kickoff_z] = missing
    return outstanding


def capture_kickoff_counts(rows: Sequence[Mapping[str, object]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        raw = str(row.get("commence_time") or "").strip()
        if not raw:
            raise ScheduleExpectationError("CAPTURE_ROW_KICKOFF_MISSING")
        try:
            kickoff = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ScheduleExpectationError("CAPTURE_ROW_KICKOFF_INVALID") from exc
        counts[iso_z(kickoff)] += 1
    return counts


def require_exact_coverage(
    rows: Sequence[Mapping[str, object]],
    expected: Counter[str],
    *,
    kind: str,
) -> None:
    actual = capture_kickoff_counts(rows)
    if actual == expected:
        return
    raise ScheduleExpectationError(
        "NFL_SCHEDULE_COVERAGE_MISMATCH:"
        + json.dumps(
            {
                "kind": kind,
                "expected": dict(sorted(expected.items())),
                "actual": dict(sorted(actual.items())),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
