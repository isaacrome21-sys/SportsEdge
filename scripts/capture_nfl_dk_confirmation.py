#!/usr/bin/env python3
"""Fail-closed, DraftKings-only NFL confirmation capture.

This lane writes the same governed evidence shape consumed by the existing NFL
confirmation validator, but never falls back to another sportsbook/provider.
Outside a frozen window, --force is proof-only and cannot write governed rows.
NOT Model_P / NOT Truth Gate / NOT OFFICIAL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.draftkings_game_market_source import (  # noqa: E402
    RawDraftKingsBoard,
    board_url,
)
from sportsedge.nfl_direct_capture_source import (  # noqa: E402
    PROVIDER,
    SOURCE_CLASS,
    SPORTSBOOK,
    DirectCaptureError,
    game_rows_direct,
)
from sportsedge.nfl_confirmation_schedule import (  # noqa: E402
    ScheduleExpectationError,
    final_expected_due_kickoffs,
    load_snapshot,
    opener_expected_kickoffs,
    require_exact_coverage,
)

SPORT = "americanfootball_nfl"
CFG_PATH = ROOT / "config/nfl_2026_capture.json"
AUTHORITY = "NOT Model_P / NOT Truth Gate / NOT OFFICIAL"


class Blocked(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_z(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def load_cfg() -> dict[str, Any]:
    return json.loads(CFG_PATH.read_text(encoding="utf-8"))


def week_of(dt_utc: datetime, cfg: Mapping[str, Any]) -> int:
    local = dt_utc.astimezone(ZoneInfo(str(cfg["timezone"]))).date()
    anchor = datetime.fromisoformat(str(cfg["week1_tuesday_local_date"])).date()
    return (local - anchor).days // 7 + 1


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_hashes() -> dict[str, str]:
    cfg = load_cfg()
    hashes = {
        "config_sha256": sha256_file(CFG_PATH),
        "policy_sha256": sha256_file(ROOT / str(cfg["policy_path"])),
        "script_sha256": sha256_file(Path(__file__)),
    }
    workflow = os.environ.get("WORKFLOW_PATH", "").strip()
    if workflow and (ROOT / workflow).is_file():
        hashes["workflow_sha256"] = sha256_file(ROOT / workflow)
    return hashes


def run_meta() -> dict[str, str | None]:
    return {
        key.lower(): os.environ.get(key)
        for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA", "GITHUB_EVENT_NAME")
    }


def fetch_once() -> tuple[RawDraftKingsBoard, str | None]:
    uri = board_url(SPORT)
    req = Request(
        uri,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 SportsEdge-DK-Market-Archive/1",
            "Referer": "https://sportsbook.draftkings.com/",
            "Origin": "https://sportsbook.draftkings.com",
        },
    )
    try:
        with urlopen(req, timeout=20) as resp:
            raw = resp.read()
            date_header = resp.headers.get("Date")
            status = getattr(resp, "status", 200)
    except HTTPError as exc:
        raise Blocked("HTTP_ERROR", f"status={exc.code}; reason={exc.reason}; url={exc.url}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise Blocked("FETCH_FAILED", type(exc).__name__) from exc
    if status == 403:
        raise Blocked("HTTP_403", "DraftKings blocked the runner")
    if not raw:
        raise Blocked("EMPTY_BOARD", "zero-byte response")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Blocked("RESPONSE_NOT_JSON", str(exc)) from exc
    if not isinstance(payload, dict):
        raise Blocked("RESPONSE_SHAPE_INVALID", type(payload).__name__)
    for key in ("events", "markets", "selections"):
        if not isinstance(payload.get(key), list):
            raise Blocked("DK_SCHEMA_MISSING", key)
    return RawDraftKingsBoard(SPORT, uri, raw, utc_now(), payload), date_header


def board_transport(board: RawDraftKingsBoard) -> dict[str, Any]:
    return {
        "source_class": SOURCE_CLASS,
        "provider": PROVIDER,
        "sportsbook": SPORTSBOOK,
        "sport_key": board.sport_key,
        "source_uri": board.source_uri,
        "observed_at_utc": iso_z(board.received_at),
        "raw_bytes": board.raw,
        "raw_sha256": hashlib.sha256(board.raw).hexdigest(),
        "raw_payload": board.payload,
    }


def atomic_create(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise Blocked("EVIDENCE_PATH_OCCUPIED", str(path))
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        with tmp.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError as exc:
            raise Blocked("EVIDENCE_PATH_OCCUPIED", str(path)) from exc
    finally:
        tmp.unlink(missing_ok=True)


def write_json(path: Path, obj: Mapping[str, Any]) -> None:
    atomic_create(path, (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def persist_raw(out_dir: Path, raw: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(raw).hexdigest()
    rel = Path("raw/draftkings-direct") / f"{digest}.json"
    path = out_dir / rel
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise Blocked("RAW_HASH_COLLISION", str(path))
    else:
        atomic_create(path, raw)
    return rel.as_posix(), digest


def _record_admissible(path: Path, cfg: Mapping[str, Any], kind: str) -> bool:
    if not path.is_file():
        return False
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if record.get("capture_kind") != kind or record.get("book") != cfg.get("bookmaker"):
        return False
    if record.get("source_class") not in (cfg.get("source_priority") or []):
        return False
    if not record.get("retrieved_at_utc") or not record.get("hashes"):
        return False
    schedule = record.get("schedule")
    if not isinstance(schedule, dict) or schedule.get("matching_semantics") != "KICKOFF_UTC_MULTIPLICITY" or not schedule.get("sha256"):
        return False
    games = record.get("games")
    return bool(games) and all(
        isinstance(game, dict)
        and game.get("spread", {}).get("status") == "OK"
        and game.get("total", {}).get("status") == "OK"
        for game in games
    )


def opener_due(cfg: Mapping[str, Any], now: datetime, snapshot: Any, out_dir: Path) -> dict[str, Any] | None:
    tz = ZoneInfo(str(cfg["timezone"]))
    local = now.astimezone(tz)
    hh, mm = map(int, str(cfg["opener_local_time"]).split(":"))
    target = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if local.strftime("%A") != cfg["opener_weekday"]:
        return None
    if not (target <= local < target + timedelta(minutes=int(cfg["opener_window_minutes"]))):
        return None
    week = week_of(now, cfg)
    if week < int(cfg["first_week"]):
        return None
    path = out_dir / f"week{week:02d}" / "opener.json"
    if _record_admissible(path, cfg, "OPENER"):
        return None
    if path.exists():
        raise Blocked("OPENER_PATH_OCCUPIED_INVALID", str(path))
    try:
        expected = opener_expected_kickoffs(dict(cfg), week, snapshot)
    except ScheduleExpectationError as exc:
        raise Blocked("SCHEDULE_BLOCKED", str(exc)) from exc
    return {"week": week, "target": target, "expected": expected, "path": path}


def determine_due(cfg: Mapping[str, Any], now: datetime, snapshot: Any, out_dir: Path) -> tuple[dict[str, Any] | None, Counter[str]]:
    opener = opener_due(cfg, now, snapshot, out_dir)
    try:
        final_expected = final_expected_due_kickoffs(dict(cfg), now, snapshot)
    except ScheduleExpectationError as exc:
        raise Blocked("SCHEDULE_BLOCKED", str(exc)) from exc
    return opener, final_expected


def select_expected(rows: list[dict[str, Any]], expected: Counter[str], *, kind: str) -> list[dict[str, Any]]:
    remaining = Counter(expected)
    selected: list[dict[str, Any]] = []
    for row in rows:
        kickoff = iso_z(parse_z(str(row.get("commence_time") or "")))
        if remaining[kickoff] > 0:
            selected.append(row)
            remaining[kickoff] -= 1
    try:
        require_exact_coverage(selected, expected, kind=kind)
    except ScheduleExpectationError as exc:
        raise Blocked("SCHEDULE_COVERAGE_MISMATCH", str(exc)) from exc
    failures = [
        {"event_id": row.get("event_id"), "spread": row.get("spread", {}).get("status"), "total": row.get("total", {}).get("status")}
        for row in selected
        if row.get("spread", {}).get("status") != "OK" or row.get("total", {}).get("status") != "OK"
    ]
    if failures:
        raise Blocked("TWO_SIDED_ADMISSION_FAILED", json.dumps(failures[:12], separators=(",", ":")))
    return selected


def schedule_meta(snapshot: Any, expected: Counter[str]) -> dict[str, Any]:
    return {
        **snapshot.provenance(),
        "expected_kickoffs": dict(sorted(expected.items())),
        "expected_game_count": sum(expected.values()),
    }


def write_missed(out_dir: Path, *, kind: str, week: int, now: datetime, reason: str, detail: str, expected: Counter[str]) -> str:
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"week{week:02d}" / "missed" / f"{kind.lower()}_{stamp}.json"
    record = {
        "authority_footer": AUTHORITY,
        "capture_kind": kind,
        "evidence_semantics": "ABSENCE_MARKER_ONLY_NOT_MARKET_DATA",
        "expected_kickoffs": dict(sorted(expected.items())),
        "no_backfill": True,
        "observed_missing_at_utc": iso_z(now),
        "reason": reason,
        "detail": detail,
        "source": "DRAFTKINGS_DIRECT_WEB_ONLY",
        "status": "MISSED_OR_BLOCKED",
        "week": week,
    }
    try:
        write_json(path, record)
    except Blocked as exc:
        if exc.reason != "EVIDENCE_PATH_OCCUPIED":
            raise
    return str(path.relative_to(ROOT))


def mark_due_missed(out_dir: Path, cfg: Mapping[str, Any], now: datetime, opener: dict[str, Any] | None, final_expected: Counter[str], reason: str, detail: str) -> list[str]:
    paths: list[str] = []
    if opener:
        paths.append(write_missed(out_dir, kind="OPENER", week=int(opener["week"]), now=now, reason=reason, detail=detail, expected=opener["expected"]))
    by_week: dict[int, Counter[str]] = {}
    for kickoff, count in final_expected.items():
        week = week_of(parse_z(kickoff), cfg)
        by_week.setdefault(week, Counter())[kickoff] += count
    for week, expected in sorted(by_week.items()):
        paths.append(write_missed(out_dir, kind="FINAL", week=week, now=now, reason=reason, detail=detail, expected=expected))
    return paths


def build_record(*, kind: str, week: int, now: datetime, board: RawDraftKingsBoard, date_header: str | None, raw_rel: str, raw_sha: str, snapshot: Any, expected: Counter[str], games: list[dict[str, Any]], target: datetime | None = None) -> dict[str, Any]:
    record = {
        "authority_footer": AUTHORITY,
        "book": SPORTSBOOK,
        "capture_kind": kind,
        "games": games,
        "hashes": current_hashes(),
        "markets": ["spreads", "totals"],
        "no_backfill": True,
        "promotion_authority": False,
        "provider": PROVIDER,
        "retrieved_at_utc": iso_z(board.received_at),
        "run": run_meta(),
        "run_started_utc": iso_z(now),
        "schedule": schedule_meta(snapshot, expected),
        "source_class": SOURCE_CLASS,
        "transport": {
            "raw_relative_path": raw_rel,
            "raw_sha256": raw_sha,
            "server_date_header": date_header,
            "source_uri": board.source_uri,
        },
        "week": week,
    }
    if target is not None:
        record["target_local"] = target.isoformat()
        record["minutes_after_target"] = round((board.received_at - target).total_seconds() / 60, 2)
    return record


def run(*, force: bool, as_of: datetime | None = None) -> dict[str, Any]:
    cfg = load_cfg()
    now = (as_of or utc_now()).astimezone(timezone.utc)
    out_dir = ROOT / str(cfg["output_dir"])
    report: dict[str, Any] = {
        "authority_footer": AUTHORITY,
        "as_of_utc": iso_z(now),
        "model_p_created": False,
        "promotion_authority": False,
    }
    try:
        snapshot = load_snapshot()
        opener, final_expected = determine_due(cfg, now, snapshot, out_dir)
    except (ScheduleExpectationError, Blocked) as exc:
        reason = exc.reason if isinstance(exc, Blocked) else "SCHEDULE_BLOCKED"
        detail = exc.detail if isinstance(exc, Blocked) else str(exc)
        report.update(status="SCHEDULE_BLOCKED", reason=reason, detail=detail)
        return report

    due = bool(opener or final_expected)
    if not due and not force:
        report.update(status="NO_WINDOW")
        return report

    try:
        board, date_header = fetch_once()
        transport = board_transport(board)
        rows = game_rows_direct(transport, week_of=lambda dt: week_of(dt, cfg))
    except (Blocked, DirectCaptureError, ValueError) as exc:
        reason = exc.reason if isinstance(exc, Blocked) else "DIRECT_PARSE_BLOCKED"
        detail = exc.detail if isinstance(exc, Blocked) else str(exc)
        missed = mark_due_missed(out_dir, cfg, now, opener, final_expected, reason, detail) if due else []
        report.update(status="MISSED_OR_BLOCKED" if due else "PROOF_BLOCKED", reason=reason, detail=detail, missed_files=missed)
        return report

    if not due:
        admitted = sum(1 for row in rows if row.get("spread", {}).get("status") == "OK" and row.get("total", {}).get("status") == "OK")
        report.update(status="PROOF_OK", rows=len(rows), admitted_rows=admitted, raw_sha256=hashlib.sha256(board.raw).hexdigest())
        return report

    try:
        raw_rel, raw_sha = persist_raw(out_dir, board.raw)
        written: list[str] = []
        if opener:
            games = select_expected(rows, opener["expected"], kind="OPENER")
            record = build_record(
                kind="OPENER", week=int(opener["week"]), now=now, board=board,
                date_header=date_header, raw_rel=raw_rel, raw_sha=raw_sha,
                snapshot=snapshot, expected=opener["expected"], games=games,
                target=opener["target"],
            )
            write_json(opener["path"], record)
            written.append(str(opener["path"].relative_to(ROOT)))

        if final_expected:
            final_games = select_expected(rows, final_expected, kind="FINAL")
            by_week: dict[int, list[dict[str, Any]]] = {}
            for row in final_games:
                by_week.setdefault(int(row["week"]), []).append(row)
            for week, games in sorted(by_week.items()):
                expected = Counter({
                    kickoff: count
                    for kickoff, count in final_expected.items()
                    if week_of(parse_z(kickoff), cfg) == week
                })
                stamp = board.received_at.strftime("%Y%m%dT%H%M%SZ")
                path = out_dir / f"week{week:02d}" / "final" / f"{stamp}.json"
                record = build_record(
                    kind="FINAL", week=week, now=now, board=board,
                    date_header=date_header, raw_rel=raw_rel, raw_sha=raw_sha,
                    snapshot=snapshot, expected=expected, games=games,
                )
                write_json(path, record)
                written.append(str(path.relative_to(ROOT)))
    except (Blocked, ScheduleExpectationError, ValueError) as exc:
        reason = exc.reason if isinstance(exc, Blocked) else "ADMISSION_BLOCKED"
        detail = exc.detail if isinstance(exc, Blocked) else str(exc)
        missed = mark_due_missed(out_dir, cfg, now, opener, final_expected, reason, detail)
        report.update(status="MISSED_OR_BLOCKED", reason=reason, detail=detail, missed_files=missed)
        return report

    report.update(
        status="CAPTURED",
        files=written,
        raw_sha256=raw_sha,
        retrieved_at_utc=iso_z(board.received_at),
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="proof parsing/admission outside frozen windows without writing governed evidence")
    parser.add_argument("--status-out", default="")
    args = parser.parse_args(argv)
    report = run(force=args.force)
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.status_out:
        target = Path(args.status_out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    return 0 if report.get("status") in {"CAPTURED", "NO_WINDOW", "PROOF_OK"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
