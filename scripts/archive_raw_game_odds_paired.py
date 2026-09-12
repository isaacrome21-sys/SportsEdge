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
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys

LEGACY_PATH = Path(__file__).with_name("archive_raw_game_odds.py")
DECISION_TARGET_MIN = 90
CLOSE_TARGET_MIN = 10
WINDOW_SEC = 8 * 60
TARGETS_MIN = (DECISION_TARGET_MIN, CLOSE_TARGET_MIN)


def _load_legacy():
    spec = importlib.util.spec_from_file_location("sportsedge_archive_raw_game_odds", LEGACY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("MLB_PAIRED_ARCHIVE_LEGACY_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.TARGETS_MIN = TARGETS_MIN
    module.WINDOW_SEC = WINDOW_SEC
    return module


def _self_test() -> int:
    legacy = _load_legacy()
    now = datetime(2026, 9, 12, 17, 0, tzinfo=timezone.utc)

    # Decision observations are confined to T-98m..T-82m, wholly inside T-120m..T-45m.
    decision_games = [
        {"gameDate": (now + timedelta(minutes=90)).isoformat()},
        {"gameDate": (now + timedelta(minutes=98)).isoformat()},
        {"gameDate": (now + timedelta(minutes=81, seconds=59)).isoformat()},
    ]
    target, eligible = legacy._eligible_games(now, decision_games)
    assert target == "T-90m", (target, eligible)
    assert len(eligible) == 2, eligible

    # Close observations are confined to T-18m..T-2m. T-1:59 and any post-start
    # observation must not qualify, so a selected row is necessarily pregame.
    close_games = [
        {"gameDate": (now + timedelta(minutes=10)).isoformat()},
        {"gameDate": (now + timedelta(minutes=18)).isoformat()},
        {"gameDate": (now + timedelta(minutes=1, seconds=59)).isoformat()},
        {"gameDate": (now - timedelta(seconds=1)).isoformat()},
    ]
    target, eligible = legacy._eligible_games(now, close_games)
    assert target == "T-10m", (target, eligible)
    assert len(eligible) == 2, eligible

    decision_lo = DECISION_TARGET_MIN - WINDOW_SEC / 60
    decision_hi = DECISION_TARGET_MIN + WINDOW_SEC / 60
    close_lo = CLOSE_TARGET_MIN - WINDOW_SEC / 60
    close_hi = CLOSE_TARGET_MIN + WINDOW_SEC / 60
    assert 45 <= decision_lo <= decision_hi <= 120
    assert 2 <= close_lo <= close_hi <= 20

    print(json.dumps({
        "status": "SELF_TEST_OK",
        "decision_window_minutes_before_start": [decision_lo, decision_hi],
        "close_window_minutes_before_start": [close_lo, close_hi],
        "post_start_capture_reachable": False,
        "promotion_authority": False,
        "historical_backfill": False,
    }, sort_keys=True))
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return _self_test()
    legacy = _load_legacy()
    return legacy.main()


if __name__ == "__main__":
    raise SystemExit(main())
