#!/usr/bin/env python3
"""Standalone append-only MLB game-odds snapshotter.

Reliability-tier contract:
- no imports from sportsedge/
- Python standard library only
- direct MLB StatsAPI schedule lookup
- direct The Odds API game-market lookup
- a status row is written for every execution
- the daily budget ledger is written before capture and after final status

The archive is deliberately duplicated from model acquisition code so model/runtime
changes cannot break the only forward data that cannot be reconstructed later.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ODDS_BASE = "https://api.the-odds-api.com/v4"
MLB_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"
SPORT_KEY = "baseball_mlb"
CT = ZoneInfo("America/Chicago")
TARGETS_MIN = (180, 90, 0)
WINDOW_SEC = 8 * 60
MARKETS = ("h2h", "spreads", "totals")
DEFAULT_CAP = 12


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(str(value))
    except Exception:
        return None


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


def _json_get(url: str, *, timeout: int = 20) -> tuple[bytes, dict[str, str]]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge-archive/1"})
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
        headers = {k.lower(): v for k, v in response.headers.items()}
        return raw, headers


def _fetch_schedule_raw(slate_date: str) -> list[dict[str, Any]]:
    params = urlencode({"sportId": 1, "date": slate_date, "hydrate": "team"})
    raw, _ = _json_get(f"{MLB_SCHEDULE}?{params}", timeout=20)
    payload = json.loads(raw)
    games: list[dict[str, Any]] = []
    for date_row in payload.get("dates", []):
        for game in date_row.get("games", []):
            game_date = game.get("gameDate")
            if not game_date:
                continue
            games.append(game)
    return games


def _parse_iso(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _eligible_games(now: datetime, games: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    best: tuple[float, str] | None = None
    labels: dict[str, list[dict[str, Any]]] = {}
    for game in games:
        try:
            start = _parse_iso(str(game["gameDate"]))
        except Exception:
            continue
        minutes_to = (start - now).total_seconds() / 60.0
        for target in TARGETS_MIN:
            delta_sec = abs((minutes_to - target) * 60.0)
            if delta_sec <= WINDOW_SEC:
                label = "T0" if target == 0 else f"T-{target}m"
                labels.setdefault(label, []).append(game)
                if best is None or delta_sec < best[0]:
                    best = (delta_sec, label)
    if best is None:
        return None, []
    return best[1], labels.get(best[1], [])


def _fetch_odds_raw(key: str, books: str) -> tuple[bytes, dict[str, str]]:
    params = {
        "apiKey": key,
        "bookmakers": books,
        "markets": ",".join(MARKETS),
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    return _json_get(f"{ODDS_BASE}/sports/{SPORT_KEY}/odds?{urlencode(params)}", timeout=20)


def _provider_events_in_window(raw: bytes, *, now: datetime, target: str) -> int:
    try:
        payload = json.loads(raw)
    except Exception:
        return 0
    if not isinstance(payload, list):
        return 0
    target_min = 0 if target == "T0" else int(target.removeprefix("T-").removesuffix("m"))
    count = 0
    for event in payload:
        try:
            start = _parse_iso(str(event["commence_time"]))
        except Exception:
            continue
        delta_sec = abs((((start - now).total_seconds() / 60.0) - target_min) * 60.0)
        if delta_sec <= WINDOW_SEC:
            count += 1
    return count


def _ledger_path() -> Path:
    return Path(os.environ.get("SPORTSEDGE_ODDS_BUDGET_LEDGER", ".cache/sportsedge/odds-budget/ledger.json"))


def _load_ledger(path: Path, *, cap: int, now: datetime) -> dict[str, Any]:
    day = now.date().isoformat()
    state: dict[str, Any] = {"utc_date": day, "cap_credits": cap, "credits_consumed_actual": 0, "runs": []}
    try:
        current = json.loads(path.read_text())
        if current.get("utc_date") == day:
            state.update(current)
    except Exception:
        pass
    state["utc_date"] = day
    state["cap_credits"] = cap
    state.setdefault("credits_consumed_actual", 0)
    state.setdefault("runs", [])
    return state


def _write_status(status_path: Path, ledger_path: Path, ledger: dict[str, Any], row: dict[str, Any]) -> None:
    _atomic_json(status_path, row)
    runs = ledger.setdefault("runs", [])
    runs.append(row)
    if len(runs) > 500:
        del runs[:-500]
    ledger["last_status"] = row.get("status")
    ledger["last_run_at_utc"] = row.get("run_at_utc")
    _atomic_json(ledger_path, ledger)


def _status_path(now: datetime) -> Path:
    stamp = now.strftime("%Y%m%dT%H%M%S.%fZ")
    return Path("artifacts/raw_odds/status") / now.date().isoformat() / f"run_{stamp}.json"


def _http_error_code(exc: HTTPError) -> tuple[str | None, str | None]:
    provider_code = None
    provider_message = None
    try:
        body = exc.read().decode("utf-8", errors="replace")
        payload = json.loads(body)
        provider_code = payload.get("error_code") or payload.get("code")
        provider_message = payload.get("message")
    except Exception:
        pass
    return provider_code, provider_message


def _final_block_status(*, exhausted_keys: int, key_count: int) -> str:
    return "BLOCKED_NO_CREDITS" if key_count > 0 and exhausted_keys == key_count else "BLOCKED_NO_ODDS"


def _self_test() -> int:
    # This path must succeed in a bare stdlib Python environment and make no network calls.
    now = datetime(2026, 8, 17, 13, 0, tzinfo=timezone.utc)
    assert _parse_iso("2026-08-17T13:00:00Z") == now
    assert _int_or_none("12") == 12
    assert set(MARKETS) == {"h2h", "spreads", "totals"}

    # Deterministic capture-window acceptance: two games are inside T-3h and one is not.
    games = [
        {"gameDate": (now + timedelta(minutes=180)).isoformat()},
        {"gameDate": (now + timedelta(minutes=184)).isoformat()},
        {"gameDate": (now + timedelta(minutes=120)).isoformat()},
    ]
    target, eligible = _eligible_games(now, games)
    assert target == "T-180m", (target, eligible)
    assert len(eligible) == 2, eligible

    # Provider exhaustion must classify distinctly from generic no-odds failure.
    assert _final_block_status(exhausted_keys=4, key_count=4) == "BLOCKED_NO_CREDITS"
    assert _final_block_status(exhausted_keys=3, key_count=4) == "BLOCKED_NO_ODDS"
    assert _final_block_status(exhausted_keys=0, key_count=0) == "BLOCKED_NO_ODDS"

    # Every execution must leave both a pre-acquisition and final ledger record.
    with TemporaryDirectory() as td:
        root = Path(td)
        ledger_path = root / "ledger.json"
        status_path = root / "status.json"
        ledger = _load_ledger(ledger_path, cap=12, now=now)
        started = {"run_at_utc": now.isoformat(), "status": "EXECUTED_STARTED"}
        final = {"run_at_utc": now.isoformat(), "status": "BLOCKED_NO_CREDITS"}
        _write_status(status_path, ledger_path, ledger, started)
        _write_status(status_path, ledger_path, ledger, final)
        persisted = json.loads(ledger_path.read_text())
        assert [row["status"] for row in persisted["runs"]] == ["EXECUTED_STARTED", "BLOCKED_NO_CREDITS"]
        assert persisted["last_status"] == "BLOCKED_NO_CREDITS"
        assert json.loads(status_path.read_text())["status"] == "BLOCKED_NO_CREDITS"

    print(json.dumps({
        "status": "SELF_TEST_OK",
        "stdlib_only": True,
        "window_math": "PASS",
        "blocked_no_credits": "PASS",
        "ledger_pre_post": "PASS",
    }))
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return _self_test()

    now = _utcnow()
    slate = now.astimezone(CT).date().isoformat()
    cap = int(os.environ.get("SPORTSEDGE_ODDS_DAILY_BUDGET_CREDITS", str(DEFAULT_CAP)))
    estimated_cost = len(MARKETS)
    ledger_path = _ledger_path()
    ledger = _load_ledger(ledger_path, cap=cap, now=now)
    status_path = _status_path(now)

    base = {
        "run_at_utc": now.isoformat(),
        "slate_date_ct": slate,
        "markets_requested": list(MARKETS),
        "request_cost_estimate": estimated_cost,
        "credits_consumed_actual": 0,
        "provider_credits_remaining": None,
        "provider_credits_used": None,
        "capture_window": None,
        "games_eligible": 0,
        "games_captured": 0,
        "capture_completeness": None,
        "counter_source": "native",
    }

    _write_status(status_path, ledger_path, ledger, {**base, "status": "EXECUTED_STARTED"})

    try:
        games = _fetch_schedule_raw(slate)
    except Exception as exc:
        row = {**base, "status": "EXECUTED_FAILED_SCHEDULE", "reason": f"{type(exc).__name__}:{exc}"}
        _write_status(status_path, ledger_path, ledger, row)
        print(json.dumps(row))
        return 4

    target, eligible = _eligible_games(now, games)
    if target is None:
        row = {**base, "status": "SKIP_OUTSIDE_CAPTURE_WINDOW", "games_scheduled": len(games)}
        _write_status(status_path, ledger_path, ledger, row)
        print(json.dumps(row))
        return 0

    base.update({"capture_window": target, "games_eligible": len(eligible), "games_scheduled": len(games)})

    keys = _keys()
    if not keys:
        row = {**base, "status": "BLOCKED_NO_ODDS_KEY"}
        _write_status(status_path, ledger_path, ledger, row)
        print(json.dumps(row))
        return 2

    consumed = int(ledger.get("credits_consumed_actual", 0) or 0)
    if consumed + estimated_cost > cap:
        row = {
            **base,
            "status": "BLOCKED_BUDGET",
            "daily_cap_credits": cap,
            "daily_credits_consumed": consumed,
            "reason": "DAILY_CREDIT_CAP_WOULD_BE_EXCEEDED",
        }
        _write_status(status_path, ledger_path, ledger, row)
        print(json.dumps(row))
        return 3

    books = os.environ.get("SPORTSEDGE_ODDS_BOOKMAKERS", "draftkings").strip() or "draftkings"
    attempts: list[dict[str, Any]] = []
    exhausted = 0
    for slot, key in enumerate(keys, start=1):
        try:
            raw, headers = _fetch_odds_raw(key, books)
            actual = _int_or_none(headers.get("x-requests-last"))
            if actual is None:
                actual = estimated_cost
            ledger["credits_consumed_actual"] = int(ledger.get("credits_consumed_actual", 0) or 0) + actual
            captured = _provider_events_in_window(raw, now=now, target=target)
            eligible_count = len(eligible)
            completeness = (captured / eligible_count) if eligible_count else None

            stamp = now.strftime("%Y%m%dT%H%M%SZ")
            outdir = Path("artifacts/raw_odds") / slate / target.replace("-", "minus")
            outdir.mkdir(parents=True, exist_ok=True)
            raw_path = outdir / f"game_odds_{stamp}.json"
            raw_path.write_bytes(raw)

            row = {
                **base,
                "status": "CAPTURED" if captured >= eligible_count else "INCOMPLETE_CAPTURE",
                "bookmakers": books,
                "key_slot": slot,
                "credits_consumed_actual": actual,
                "daily_credits_consumed": ledger["credits_consumed_actual"],
                "provider_credits_remaining": _int_or_none(headers.get("x-requests-remaining")),
                "provider_credits_used": _int_or_none(headers.get("x-requests-used")),
                "games_captured": captured,
                "capture_completeness": completeness,
                "raw_file": str(raw_path),
            }
            _write_status(status_path, ledger_path, ledger, row)
            print(json.dumps(row))
            return 0 if row["status"] == "CAPTURED" else 5
        except HTTPError as exc:
            provider_code, provider_message = _http_error_code(exc)
            if exc.code == 401 and provider_code == "OUT_OF_USAGE_CREDITS":
                exhausted += 1
            attempts.append({
                "key_slot": slot,
                "http_status": exc.code,
                "provider_code": provider_code,
                "provider_message": provider_message,
            })
        except URLError as exc:
            attempts.append({"key_slot": slot, "reason": f"URLError:{exc.reason}"})
        except Exception as exc:
            attempts.append({"key_slot": slot, "reason": f"{type(exc).__name__}:{exc}"})

    status = _final_block_status(exhausted_keys=exhausted, key_count=len(keys))
    row = {**base, "status": status, "attempts": attempts}
    _write_status(status_path, ledger_path, ledger, row)
    print(json.dumps(row))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
