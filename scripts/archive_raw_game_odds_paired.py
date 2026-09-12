#!/usr/bin/env python3
"""Safe paired-window wrapper for the append-only MLB game-odds archive.

This wrapper intentionally reuses the standalone stdlib archive implementation while
narrowing paid observations to the two pregame windows that can feed a future paired
closing-price evidence path:

- decision candidate: T-90m +/- 8m (inside frozen T-120m..T-45m decision window)
- close candidate: T-10m +/- 8m (inside frozen T-20m..T-2m pregame close window)

Raw captures remain observations only. This module creates no Model_P, promotion
authority, market eligibility, Truth Gate PASS, edge floor, or historical backfill.
The legacy T0 +/- 8m window is deliberately unreachable here because it can include
post-scheduled-start observations.

Use --plan for a free StatsAPI-only readiness check. Plan mode never calls the odds
provider, never reads or writes the paid-credit ledger, and never creates evidence.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

LEGACY_PATH = Path(__file__).with_name("archive_raw_game_odds.py")
DECISION_TARGET_MIN = 90
CLOSE_TARGET_MIN = 10
WINDOW_SEC = 8 * 60
TARGETS_MIN = (DECISION_TARGET_MIN, CLOSE_TARGET_MIN)


def _capture_role(window: Any) -> str:
    if window == "T-90m":
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

    # Bind the exact raw response bytes into both the durable status row and the
    # daily ledger before either is written. This is provenance only; it grants
    # no promotion authority and does not transform the provider payload.
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


def _plan_row(legacy: Any, game: dict[str, Any]) -> dict[str, Any]:
    start = legacy._parse_iso(str(game["gameDate"]))
    windows: dict[str, dict[str, str]] = {}
    for target in TARGETS_MIN:
        label = "T0" if target == 0 else f"T-{target}m"
        center = start - timedelta(minutes=target)
        windows[label] = {
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
    target, eligible = legacy._eligible_games(now, games)
    due_ids = {game.get("gamePk") for game in eligible}
    schedule = [_plan_row(legacy, game) for game in games]
    due_games = [row for row in schedule if row.get("game_pk") in due_ids] if target else []
    return {
        "status": "CAPTURE_DUE" if target else "OUTSIDE_CAPTURE_WINDOW",
        "planned_at_utc": now.isoformat(),
        "slate_date_ct": slate,
        "capture_window": target,
        "capture_role": _capture_role(target) if target else None,
        "games_scheduled": len(games),
        "games_eligible": len(eligible),
        "due_games": due_games,
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


def _self_test() -> int:
    legacy = _load_legacy()
    now = datetime(2026, 9, 12, 17, 0, tzinfo=timezone.utc)

    # Decision observations are confined to T-98m..T-82m, wholly inside T-120m..T-45m.
    decision_games = [
        {"gamePk": 1, "gameDate": (now + timedelta(minutes=90)).isoformat()},
        {"gamePk": 2, "gameDate": (now + timedelta(minutes=98)).isoformat()},
        {"gamePk": 3, "gameDate": (now + timedelta(minutes=81, seconds=59)).isoformat()},
    ]
    target, eligible = legacy._eligible_games(now, decision_games)
    assert target == "T-90m", (target, eligible)
    assert len(eligible) == 2, eligible

    # Close observations are confined to T-18m..T-2m. T-1:59 and any post-start
    # observation must not qualify, so a selected row is necessarily pregame.
    close_games = [
        {"gamePk": 4, "gameDate": (now + timedelta(minutes=10)).isoformat()},
        {"gamePk": 5, "gameDate": (now + timedelta(minutes=18)).isoformat()},
        {"gamePk": 6, "gameDate": (now + timedelta(minutes=1, seconds=59)).isoformat()},
        {"gamePk": 7, "gameDate": (now - timedelta(seconds=1)).isoformat()},
    ]
    target, eligible = legacy._eligible_games(now, close_games)
    assert target == "T-10m", (target, eligible)
    assert len(eligible) == 2, eligible

    # Plan construction is deterministic and carries no paid/evidence authority.
    plan = _build_plan(legacy, now=now, slate="2026-09-12", games=decision_games)
    assert plan["status"] == "CAPTURE_DUE"
    assert plan["capture_role"] == "DECISION_CANDIDATE"
    assert plan["games_eligible"] == 2
    assert plan["sportsbook_request_attempted"] is False
    assert plan["budget_ledger_touched"] is False
    assert plan["promotion_authority"] is False
    assert plan["model_p"] is None

    decision_lo = DECISION_TARGET_MIN - WINDOW_SEC / 60
    decision_hi = DECISION_TARGET_MIN + WINDOW_SEC / 60
    close_lo = CLOSE_TARGET_MIN - WINDOW_SEC / 60
    close_hi = CLOSE_TARGET_MIN + WINDOW_SEC / 60
    assert 45 <= decision_lo <= decision_hi <= 120
    assert 2 <= close_lo <= close_hi <= 20
    assert _capture_role("T-90m") == "DECISION_CANDIDATE"
    assert _capture_role("T-10m") == "CLOSE_CANDIDATE"

    print(json.dumps({
        "status": "SELF_TEST_OK",
        "decision_window_minutes_before_start": [decision_lo, decision_hi],
        "close_window_minutes_before_start": [close_lo, close_hi],
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
    legacy = _load_legacy()
    return legacy.main()


if __name__ == "__main__":
    raise SystemExit(main())
