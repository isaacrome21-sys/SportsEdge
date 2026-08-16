#!/usr/bin/env python3
"""Append-only raw MLB game-odds snapshotter.

Captures only featured game markets (h2h, spreads, totals) at narrow target
windows around each game's first pitch. Payload is written raw so later schema
changes cannot corrupt historical replay. No sportsbook data enters Model_P.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from sportsedge.mlb_source import fetch_schedule, parse_game_start
from sportsedge.odds_budget import OddsBudgetError, assert_budget_available, load_budget, record_actual_cost

BASE = "https://api.the-odds-api.com/v4"
SPORT_KEY = "baseball_mlb"
CT = ZoneInfo("America/Chicago")
TARGETS_MIN = (180, 90, 0)
WINDOW_SEC = 8 * 60
MARKETS = ("h2h", "spreads", "totals")


def _keys() -> list[str]:
    out: list[str] = []
    for name in (
        "SPORTSEDGE_ODDS_API_KEY",
        "SPORTSEDGE_ODDS_API_KEY_2",
        "SPORTSEDGE_ODDS_API_KEY_3",
        "SPORTSEDGE_ODDS_API_KEY_4",
    ):
        value = os.environ.get(name, "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _target_label(now: datetime, schedule) -> str | None:
    best: tuple[float, str] | None = None
    for game in schedule:
        start = parse_game_start(game.game_date).astimezone(timezone.utc)
        minutes_to = (start - now).total_seconds() / 60.0
        for target in TARGETS_MIN:
            delta_sec = abs((minutes_to - target) * 60.0)
            if delta_sec <= WINDOW_SEC:
                label = "T0" if target == 0 else f"T-{target}m"
                if best is None or delta_sec < best[0]:
                    best = (delta_sec, label)
    return None if best is None else best[1]


def _fetch_raw(key: str, books: str):
    params = {
        "apiKey": key,
        "bookmakers": books,
        "markets": ",".join(MARKETS),
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    url = f"{BASE}/sports/{SPORT_KEY}/odds?{urlencode(params)}"
    with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=20) as response:
        raw = response.read()
        headers = {k.lower(): v for k, v in response.headers.items()}
        return raw, headers


def main() -> int:
    now = datetime.now(timezone.utc)
    slate = now.astimezone(CT).date().isoformat()
    schedule = fetch_schedule(slate)
    target = _target_label(now, schedule)
    if target is None:
        print(json.dumps({"status": "SKIP_OUTSIDE_CAPTURE_WINDOW", "slate_date_ct": slate}))
        return 0

    keys = _keys()
    if not keys:
        print(json.dumps({"status": "BLOCKED_NO_ODDS_KEY"}))
        return 2

    cap = int(os.environ.get("SPORTSEDGE_ODDS_DAILY_BUDGET_CREDITS", "12"))
    ledger = Path(os.environ.get("SPORTSEDGE_ODDS_BUDGET_LEDGER", ".cache/sportsedge/odds-budget/ledger.json"))
    state = load_budget(ledger, cap_credits=cap, now=now)
    estimated_cost = len(MARKETS)
    try:
        assert_budget_available(state, estimated_cost=estimated_cost)
    except OddsBudgetError as exc:
        print(json.dumps({"status": "BLOCKED_BUDGET", "reason": str(exc)}))
        return 3

    books = os.environ.get("SPORTSEDGE_ODDS_BOOKMAKERS", "draftkings").strip() or "draftkings"
    attempts = []
    for slot, key in enumerate(keys, start=1):
        try:
            raw, headers = _fetch_raw(key, books)
            actual = int(headers.get("x-requests-last", estimated_cost))
            state = record_actual_cost(ledger, state=state, actual_cost=actual, provider_headers=headers)
            stamp = now.strftime("%Y%m%dT%H%M%SZ")
            outdir = Path("artifacts/raw_odds") / slate / target.replace("-", "minus")
            outdir.mkdir(parents=True, exist_ok=True)
            raw_path = outdir / f"game_odds_{stamp}.json"
            meta_path = outdir / f"game_odds_{stamp}.meta.json"
            raw_path.write_bytes(raw)
            meta = {
                "captured_at_utc": now.isoformat(),
                "slate_date_ct": slate,
                "capture_window": target,
                "bookmakers": books,
                "markets_requested": list(MARKETS),
                "credits_consumed_actual": actual,
                "request_cost_estimate": estimated_cost,
                "provider_credits_remaining": _int_or_none(headers.get("x-requests-remaining")),
                "provider_credits_used": _int_or_none(headers.get("x-requests-used")),
                "key_slot": slot,
                "raw_file": str(raw_path),
            }
            meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
            print(json.dumps({"status": "CAPTURED", **meta}))
            return 0
        except Exception as exc:
            attempts.append({"key_slot": slot, "reason": f"{type(exc).__name__}:{exc}"})

    print(json.dumps({"status": "BLOCKED_NO_ODDS", "attempts": attempts}))
    return 2


def _int_or_none(value):
    try:
        return int(str(value))
    except Exception:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
