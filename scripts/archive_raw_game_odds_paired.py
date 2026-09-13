#!/usr/bin/env python3
"""Safe paired-window wrapper for the append-only MLB game-odds archive.

Paid observations are restricted to three wholly pregame windows:
- T-90m +/- 8m: early decision candidate
- T-55m +/- 8m: late lineup-bound decision candidate
- T-10m +/- 8m: close candidate

Raw captures are observations only. They create no Model_P, promotion authority,
market eligibility, Truth Gate PASS, edge floor, or historical backfill.

The wrapper also fail-closes if different games are simultaneously due in different
capture windows. The legacy selector returns one best label globally; without this
guard a paid response could silently omit another due window while still looking
complete for the selected label.

Use --plan for a free StatsAPI-only readiness check. Plan mode never calls the odds
provider, never reads or writes the paid-credit ledger, and never creates evidence.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any

LEGACY_PATH = Path(__file__).with_name("archive_raw_game_odds.py")
EARLY_DECISION_TARGET_MIN = 90
LATE_DECISION_TARGET_MIN = 55
CLOSE_TARGET_MIN = 10
WINDOW_SEC = 8 * 60
TARGETS_MIN = (EARLY_DECISION_TARGET_MIN, LATE_DECISION_TARGET_MIN, CLOSE_TARGET_MIN)


def _label(target: int) -> str:
    return "T0" if target == 0 else f"T-{target}m"


def _capture_role(window: Any) -> str:
    if window in {"T-90m", "T-55m"}:
        return "DECISION_CANDIDATE"
    if window == "T-10m":
        return "CLOSE_CANDIDATE"
    raise RuntimeError(f"MLB_PAIRED_ARCHIVE_UNKNOWN_WINDOW:{window}")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _bind_raw_provenance(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("status") not in {"CAPTURED", "INCOMPLETE_CAPTURE"}:
        return row
    raw_value = row.get("raw_file")
    if not raw_value:
        raise RuntimeError("MLB_PAIRED_ARCHIVE_RAW_FILE_MISSING")
    raw_path = Path(str(raw_value))
    if not raw_path.is_file():
        raise RuntimeError(f"MLB_PAIRED_ARCHIVE_RAW_FILE_NOT_FOUND:{raw_path}")
    enriched = dict(row)
    enriched.update(
        capture_role=_capture_role(row.get("capture_window")),
        raw_sha256=_sha256_file(raw_path),
        raw_bytes=raw_path.stat().st_size,
        evidence_class="RAW_OBSERVATION_NOT_PROMOTION_EVIDENCE",
        promotion_authority=False,
        may_change_market_eligibility=False,
        model_p=None,
    )
    return enriched


def _load_legacy():
    spec = importlib.util.spec_from_file_location("sportsedge_archive_raw_game_odds", LEGACY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("MLB_PAIRED_ARCHIVE_LEGACY_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.TARGETS_MIN = TARGETS_MIN
    module.WINDOW_SEC = WINDOW_SEC

    original_write_status = module._write_status

    def write_status_with_provenance(status_path, ledger_path, ledger, row):
        original_write_status(status_path, ledger_path, ledger, _bind_raw_provenance(row))

    module._write_status = write_status_with_provenance
    return module


def _team_name(game: dict[str, Any], side: str) -> str | None:
    try:
        return str(game["teams"][side]["team"]["name"])
    except Exception:
        return None


def _due_windows(legacy: Any, *, now: datetime, games: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    due: dict[str, list[dict[str, Any]]] = {}
    for game in games:
        try:
            start = legacy._parse_iso(str(game["gameDate"]))
        except Exception:
            continue
        minutes_to = (start - now).total_seconds() / 60.0
        for target in TARGETS_MIN:
            if abs((minutes_to - target) * 60.0) <= WINDOW_SEC:
                due.setdefault(_label(target), []).append(game)
    return due


def _plan_row(legacy: Any, game: dict[str, Any]) -> dict[str, Any]:
    start = legacy._parse_iso(str(game["gameDate"]))
    windows: dict[str, dict[str, str]] = {}
    for target in TARGETS_MIN:
        center = start - timedelta(minutes=target)
        windows[_label(target)] = {
            "opens_utc": (center - timedelta(seconds=WINDOW_SEC)).isoformat(),
            "center_utc": center.isoformat(),
            "closes_utc": (center + timedelta(seconds=WINDOW_SEC)).isoformat(),
        }
    return {
        "game_pk": game.get("gamePk"),
        "official_start_utc": start.isoformat(),
        "away_team": _team_name(game, "away"),
        "home_team": _team_name(game, "home"),
        "capture_windows": windows,
    }


def _build_plan(legacy: Any, *, now: datetime, slate: str, games: list[dict[str, Any]]) -> dict[str, Any]:
    due = _due_windows(legacy, now=now, games=games)
    schedule = [_plan_row(legacy, game) for game in games]
    due_summary = {
        label: [row for row in schedule if row.get("game_pk") in {g.get("gamePk") for g in rows}]
        for label, rows in due.items()
    }
    overlap = len(due) > 1
    only_label = next(iter(due)) if len(due) == 1 else None
    only_games = due.get(only_label, []) if only_label else []
    return {
        "status": "OVERLAPPING_CAPTURE_WINDOWS" if overlap else ("CAPTURE_DUE" if due else "OUTSIDE_CAPTURE_WINDOW"),
        "planned_at_utc": now.isoformat(),
        "slate_date_ct": slate,
        "capture_window": only_label,
        "capture_role": _capture_role(only_label) if only_label else None,
        "due_windows": due_summary,
        "games_scheduled": len(games),
        "games_eligible": len(only_games) if only_label else sum(len(v) for v in due.values()),
        "due_games": due_summary.get(only_label, []) if only_label else [],
        "schedule": schedule,
        "source": "MLB_STATSAPI_SCHEDULE_ONLY",
        "sportsbook_request_attempted": False,
        "budget_ledger_touched": False,
        "evidence_class": "READINESS_PLAN_NOT_EVIDENCE",
        "promotion_authority": False,
        "may_change_market_eligibility": False,
        "model_p": None,
    }


def _plan_only() -> int:
    legacy = _load_legacy()
    now = legacy._utcnow()
    slate = now.astimezone(legacy.CT).date().isoformat()
    try:
        games = legacy._fetch_schedule_raw(slate)
    except Exception as exc:
        payload = {
            "status": "PLAN_FAILED_SCHEDULE",
            "planned_at_utc": now.isoformat(),
            "slate_date_ct": slate,
            "reason": f"{type(exc).__name__}:{exc}",
            "sportsbook_request_attempted": False,
            "budget_ledger_touched": False,
            "evidence_class": "READINESS_PLAN_NOT_EVIDENCE",
            "promotion_authority": False,
            "may_change_market_eligibility": False,
            "model_p": None,
        }
        print(json.dumps(payload, sort_keys=True))
        return 4
    print(json.dumps(_build_plan(legacy, now=now, slate=slate, games=games), sort_keys=True))
    return 0


def _write_overlap_block(legacy: Any, *, now: datetime, slate: str, due: dict[str, list[dict[str, Any]]]) -> int:
    cap = int(os.environ.get("SPORTSEDGE_ODDS_DAILY_BUDGET_CREDITS", str(legacy.DEFAULT_CAP)))
    ledger_path = legacy._ledger_path()
    ledger = legacy._load_ledger(ledger_path, cap=cap, now=now)
    status_path = legacy._status_path(now)
    row = {
        "run_at_utc": now.isoformat(),
        "slate_date_ct": slate,
        "status": "BLOCKED_OVERLAPPING_CAPTURE_WINDOWS",
        "due_windows": {label: [g.get("gamePk") for g in rows] for label, rows in due.items()},
        "games_eligible": sum(len(rows) for rows in due.values()),
        "sportsbook_request_attempted": False,
        "credits_consumed_actual": 0,
        "evidence_class": "CAPTURE_GUARD_NOT_EVIDENCE",
        "promotion_authority": False,
        "may_change_market_eligibility": False,
        "model_p": None,
        "reason": "MULTIPLE_CAPTURE_ROLES_DUE_SINGLE_LEGACY_SELECTOR_UNSAFE",
    }
    legacy._write_status(status_path, ledger_path, ledger, row)
    print(json.dumps(row, sort_keys=True))
    return 6


def _runtime_capture() -> int:
    legacy = _load_legacy()
    now = legacy._utcnow()
    slate = now.astimezone(legacy.CT).date().isoformat()
    try:
        games = legacy._fetch_schedule_raw(slate)
    except Exception:
        return legacy.main()
    due = _due_windows(legacy, now=now, games=games)
    if len(due) > 1:
        return _write_overlap_block(legacy, now=now, slate=slate, due=due)

    # Reuse the exact schedule snapshot used by the overlap guard so target selection
    # and the paid capture cannot disagree because of a second schedule fetch.
    legacy._fetch_schedule_raw = lambda _slate: games
    return legacy.main()


def _self_test() -> int:
    legacy = _load_legacy()
    now = datetime(2026, 9, 12, 17, 0, tzinfo=timezone.utc)

    early = [
        {"gamePk": 1, "gameDate": (now + timedelta(minutes=90)).isoformat()},
        {"gamePk": 2, "gameDate": (now + timedelta(minutes=98)).isoformat()},
        {"gamePk": 3, "gameDate": (now + timedelta(minutes=81, seconds=59)).isoformat()},
    ]
    target, eligible = legacy._eligible_games(now, early)
    assert target == "T-90m" and len(eligible) == 2

    late = [
        {"gamePk": 8, "gameDate": (now + timedelta(minutes=55)).isoformat()},
        {"gamePk": 9, "gameDate": (now + timedelta(minutes=63)).isoformat()},
        {"gamePk": 10, "gameDate": (now + timedelta(minutes=46, seconds=59)).isoformat()},
    ]
    target, eligible = legacy._eligible_games(now, late)
    assert target == "T-55m" and len(eligible) == 2

    close = [
        {"gamePk": 4, "gameDate": (now + timedelta(minutes=10)).isoformat()},
        {"gamePk": 5, "gameDate": (now + timedelta(minutes=18)).isoformat()},
        {"gamePk": 6, "gameDate": (now + timedelta(minutes=1, seconds=59)).isoformat()},
        {"gamePk": 7, "gameDate": (now - timedelta(seconds=1)).isoformat()},
    ]
    target, eligible = legacy._eligible_games(now, close)
    assert target == "T-10m" and len(eligible) == 2

    overlap_games = [
        {"gamePk": 11, "gameDate": (now + timedelta(minutes=55)).isoformat()},
        {"gamePk": 12, "gameDate": (now + timedelta(minutes=10)).isoformat()},
    ]
    due = _due_windows(legacy, now=now, games=overlap_games)
    assert set(due) == {"T-55m", "T-10m"}
    plan = _build_plan(legacy, now=now, slate="2026-09-12", games=overlap_games)
    assert plan["status"] == "OVERLAPPING_CAPTURE_WINDOWS"
    assert plan["sportsbook_request_attempted"] is False
    assert plan["promotion_authority"] is False

    early_lo = EARLY_DECISION_TARGET_MIN - WINDOW_SEC / 60
    early_hi = EARLY_DECISION_TARGET_MIN + WINDOW_SEC / 60
    late_lo = LATE_DECISION_TARGET_MIN - WINDOW_SEC / 60
    late_hi = LATE_DECISION_TARGET_MIN + WINDOW_SEC / 60
    close_lo = CLOSE_TARGET_MIN - WINDOW_SEC / 60
    close_hi = CLOSE_TARGET_MIN + WINDOW_SEC / 60
    assert 45 <= early_lo <= early_hi <= 120
    assert 45 <= late_lo <= late_hi <= 120
    assert late_lo > close_hi
    assert 2 <= close_lo <= close_hi <= 20

    print(json.dumps({
        "status": "SELF_TEST_OK",
        "early_decision_window_minutes_before_start": [early_lo, early_hi],
        "late_decision_window_minutes_before_start": [late_lo, late_hi],
        "close_window_minutes_before_start": [close_lo, close_hi],
        "overlap_guard": True,
        "overlap_paid_request_reachable": False,
        "post_start_capture_reachable": False,
        "raw_sha256_bound_on_capture": True,
        "capture_role_bound_on_capture": True,
        "free_plan_mode": True,
        "promotion_authority": False,
        "historical_backfill": False,
    }, sort_keys=True))
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return _self_test()
    if "--plan" in sys.argv:
        return _plan_only()
    return _runtime_capture()


if __name__ == "__main__":
    raise SystemExit(main())
