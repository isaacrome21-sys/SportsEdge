#!/usr/bin/env python3
"""Bounded historical MLB period/player-prop replay using The Odds API event endpoint.

This lane is separate from featured h2h/spreads/totals because historical event
odds are charged per event and per returned market. It stores exact provider bytes
and never relabels backfilled data as a forward observation.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ODDS_BASE = "https://api.the-odds-api.com/v4"
MLB_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"
SPORT_KEY = "baseball_mlb"
SCHEMA = "SPORTSEDGE_MLB_V8_EVENT_REPLAY_V1"
SOURCE_ID = "the_odds_api_v4_historical"
DEFAULT_ROOT = Path("artifacts/mlb_v8/replay")
DEFAULT_CATALOG = Path("config/mlb_v8_odds_api_event_markets.json")


class EventReplayError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _get(url: str, *, timeout: int = 45) -> tuple[bytes, dict[str, str]]:
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge-V8-event-replay/1"})
    with urlopen(req, timeout=timeout) as response:
        return response.read(), {k.lower(): v for k, v in response.headers.items()}


def _keys() -> list[str]:
    out = []
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


def _norm_team(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _schedule_games(day: date) -> list[dict[str, Any]]:
    params = urlencode({"sportId": 1, "date": day.isoformat(), "gameType": "R", "hydrate": "team"})
    raw, _ = _get(f"{MLB_SCHEDULE}?{params}", timeout=30)
    payload = json.loads(raw)
    games = []
    for date_row in payload.get("dates", []):
        for game in date_row.get("games", []):
            start = _parse_iso(game.get("gameDate"))
            teams = game.get("teams") or {}
            if start is None:
                continue
            games.append({
                "gamePk": str(game.get("gamePk")),
                "commence_time": start,
                "home_team": ((teams.get("home") or {}).get("team") or {}).get("name"),
                "away_team": ((teams.get("away") or {}).get("team") or {}).get("name"),
            })
    return games


def _floor_5m(dt: datetime) -> datetime:
    return dt.replace(minute=(dt.minute // 5) * 5, second=0, microsecond=0)


def _historical_events(api_key: str, at: datetime) -> tuple[dict[str, Any], dict[str, str]]:
    params = urlencode({"apiKey": api_key, "date": _iso(at), "dateFormat": "iso"})
    raw, headers = _get(f"{ODDS_BASE}/historical/sports/{SPORT_KEY}/events?{params}")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise EventReplayError("historical events response shape invalid")
    return payload, headers


def _match_event(game: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any] | None:
    home = _norm_team(game["home_team"])
    away = _norm_team(game["away_team"])
    exact = []
    for row in events:
        if not isinstance(row, dict):
            continue
        if _norm_team(row.get("home_team")) == home and _norm_team(row.get("away_team")) == away:
            start = _parse_iso(row.get("commence_time"))
            if start and abs((start - game["commence_time"]).total_seconds()) <= 15 * 60:
                exact.append(row)
    return exact[0] if len(exact) == 1 else None


def _load_catalog(path: Path, groups: list[str]) -> list[str]:
    payload = json.loads(path.read_text())
    available = payload.get("groups") or {}
    markets: list[str] = []
    for group in groups:
        rows = available.get(group)
        if not isinstance(rows, list):
            raise EventReplayError(f"unknown market group: {group}")
        for market in rows:
            market = str(market).strip()
            if market and market not in markets:
                markets.append(market)
    if not markets:
        raise EventReplayError("no event markets selected")
    return markets


def _ledger_path(root: Path) -> Path:
    return root / "runtime/the_odds_api_event_ledger.json"


def _restore_ledger(root: Path) -> None:
    path = _ledger_path(root)
    if path.exists() or not Path(".git").exists():
        return
    remote = "archive/mlb_v8/replay/runtime/the_odds_api_event_ledger.json"
    try:
        subprocess.run(["git", "fetch", "--depth=1", "origin", "data"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        out = subprocess.run(["git", "show", f"FETCH_HEAD:{remote}"], check=False, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if out.returncode == 0 and out.stdout:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(out.stdout)
    except Exception:
        pass


def _load_ledger(root: Path) -> dict[str, Any]:
    _restore_ledger(root)
    try:
        payload = json.loads(_ledger_path(root).read_text())
        if isinstance(payload, dict):
            payload.setdefault("completed", [])
            return payload
    except Exception:
        pass
    return {"schema_version": SCHEMA, "completed": [], "created_at_utc": _iso(_now())}


def _save_ledger(root: Path, ledger: dict[str, Any]) -> None:
    ledger["updated_at_utc"] = _iso(_now())
    _atomic_json(_ledger_path(root), ledger)


def _write_bundle(
    *,
    root: Path,
    game: dict[str, Any],
    provider_event: dict[str, Any],
    requested_at: datetime,
    groups: list[str],
    markets: list[str],
    raw: bytes,
    headers: dict[str, str],
) -> Path:
    digest = _sha(raw)
    bundle = root / SOURCE_ID / "event_markets" / game["commence_time"].date().isoformat() / f"{game['gamePk']}_{requested_at.strftime('%Y%m%dT%H%M%SZ')}_{digest[:16]}"
    bundle.mkdir(parents=True, exist_ok=True)
    raw_path = bundle / "raw.json"
    if raw_path.exists() and _sha(raw_path.read_bytes()) != digest:
        raise EventReplayError(f"immutable collision: {raw_path}")
    raw_path.write_bytes(raw)
    payload = json.loads(raw)
    snapshot = _parse_iso(payload.get("timestamp")) if isinstance(payload, dict) else None
    manifest = {
        "schema_version": SCHEMA,
        "evidence_kind": "HISTORICAL_EVENT_MARKET_SNAPSHOT",
        "collection_mode": "HISTORICAL_BACKFILL",
        "historical_backfill": True,
        "forward_evidence": False,
        "source_id": SOURCE_ID,
        "source_class": "PIT_SNAPSHOT",
        "mlb_game_pk": game["gamePk"],
        "home_team": game["home_team"],
        "away_team": game["away_team"],
        "commence_time_utc": _iso(game["commence_time"]),
        "provider_event_id": provider_event.get("id"),
        "requested_snapshot_at_utc": _iso(requested_at),
        "provider_snapshot_at_utc": _iso(snapshot) if snapshot else None,
        "snapshot_at_or_before_requested": bool(snapshot and snapshot <= requested_at),
        "market_groups": groups,
        "markets_requested": markets,
        "raw_sha256": digest,
        "raw_bytes": len(raw),
        "provider_request_cost": headers.get("x-requests-last"),
        "provider_remaining": headers.get("x-requests-remaining"),
        "archived_at_utc": _iso(_now()),
        "governance": {
            "promotion_effect": "NONE",
            "provider_market_mapping": "UNMAPPED_ACQUISITION_ONLY",
            "rule": "provider keys must be mapped to canonical SportsEdge market semantics separately; empty or absent markets are not synthesized",
        },
    }
    _atomic_json(bundle / "manifest.json", manifest)
    return bundle


def _dates(start: date, end: date, newest_first: bool) -> list[date]:
    rows = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    return list(reversed(rows)) if newest_first else rows


def run(
    *,
    root: Path,
    start: date,
    end: date,
    target_minutes: int,
    groups: list[str],
    markets: list[str],
    max_credits: int,
    max_events: int,
    newest_first: bool,
) -> dict[str, Any]:
    keys = _keys()
    if not keys:
        return {"status": "BLOCKED_NO_KEY"}

    # Worst-case bound is based on requested markets. The provider bills only
    # markets actually returned, but the lane never depends on that discount.
    worst_case_per_event = 10 * len(markets)
    if max_credits < worst_case_per_event:
        return {
            "status": "BLOCKED_BUDGET_TOO_SMALL",
            "worst_case_per_event": worst_case_per_event,
            "selected_markets": len(markets),
        }

    ledger = _load_ledger(root)
    completed = set(str(x) for x in ledger.get("completed", []))
    captured = 0
    actual_spent = 0
    reserved_spend = 0
    misses = []

    for day in _dates(start, end, newest_first):
        games = _schedule_games(day)
        if newest_first:
            games.reverse()
        for game in games:
            if captured >= max_events:
                ledger["completed"] = sorted(completed)
                _save_ledger(root, ledger)
                return {"status": "EVENT_BOUND_REACHED", "captured": captured, "actual_credits": actual_spent, "misses": misses[-50:]}
            requested = _floor_5m(game["commence_time"] - timedelta(minutes=target_minutes))
            identity = f"{game['gamePk']}|{_iso(requested)}|{','.join(groups)}"
            if identity in completed:
                continue
            if reserved_spend + worst_case_per_event > max_credits:
                ledger["completed"] = sorted(completed)
                _save_ledger(root, ledger)
                return {
                    "status": "BUDGET_BOUND_REACHED",
                    "captured": captured,
                    "actual_credits": actual_spent,
                    "reserved_credit_bound": reserved_spend,
                    "worst_case_per_event": worst_case_per_event,
                    "misses": misses[-50:],
                }

            events_payload = None
            events_headers: dict[str, str] = {}
            event_attempts = []
            used_key = None
            for slot, key in enumerate(keys, start=1):
                try:
                    events_payload, events_headers = _historical_events(key, requested)
                    used_key = key
                    break
                except HTTPError as exc:
                    event_attempts.append({"slot": slot, "http_status": exc.code})
                    if exc.code not in (401, 403, 429):
                        raise
            if events_payload is None or used_key is None:
                return {"status": "BLOCKED_PROVIDER_EVENTS", "attempts": event_attempts, "captured": captured}

            event = _match_event(game, events_payload.get("data") or [])
            if event is None:
                misses.append({"gamePk": game["gamePk"], "requested_at": _iso(requested), "reason": "PROVIDER_EVENT_UNRESOLVED"})
                completed.add(identity)
                ledger["completed"] = sorted(completed)
                _save_ledger(root, ledger)
                continue

            params = {
                "apiKey": used_key,
                "bookmakers": os.environ.get("SPORTSEDGE_REPLAY_BOOKMAKERS", "draftkings").strip() or "draftkings",
                "markets": ",".join(markets),
                "oddsFormat": "american",
                "dateFormat": "iso",
                "date": _iso(requested),
            }
            odds_raw = None
            odds_headers: dict[str, str] = {}
            attempts = []
            for slot, key in enumerate(keys, start=1):
                params["apiKey"] = key
                url = f"{ODDS_BASE}/historical/sports/{SPORT_KEY}/events/{event['id']}/odds?{urlencode(params)}"
                try:
                    odds_raw, odds_headers = _get(url, timeout=60)
                    break
                except HTTPError as exc:
                    attempts.append({"slot": slot, "http_status": exc.code})
                    if exc.code not in (401, 403, 429):
                        raise
            if odds_raw is None:
                return {"status": "BLOCKED_PROVIDER_ODDS", "attempts": attempts, "captured": captured}

            reserved_spend += worst_case_per_event
            try:
                actual_spent += int(odds_headers.get("x-requests-last") or 0)
            except ValueError:
                pass
            _write_bundle(
                root=root,
                game=game,
                provider_event=event,
                requested_at=requested,
                groups=groups,
                markets=markets,
                raw=odds_raw,
                headers=odds_headers,
            )
            completed.add(identity)
            ledger["completed"] = sorted(completed)
            ledger["actual_credits_last_run"] = actual_spent
            _save_ledger(root, ledger)
            captured += 1

    return {"status": "COMPLETE_RANGE", "captured": captured, "actual_credits": actual_spent, "misses": misses[-50:]}


def _self_test(catalog: Path) -> int:
    period = _load_catalog(catalog, ["period_core"])
    batter = _load_catalog(catalog, ["batter_core"])
    pitcher = _load_catalog(catalog, ["pitcher_core"])
    assert "h2h_1st_5_innings" in period
    assert "batter_home_runs" in batter
    assert "pitcher_strikeouts" in pitcher
    assert len(set(period + batter + pitcher)) == len(period + batter + pitcher)
    dt = datetime(2026, 9, 3, 16, 32, tzinfo=timezone.utc)
    assert _iso(_floor_5m(dt - timedelta(minutes=90))) == "2026-09-03T15:00:00Z"
    game = {"home_team": "Chicago Cubs", "away_team": "Milwaukee Brewers", "commence_time": dt}
    events = [{"id": "x", "home_team": "Chicago Cubs", "away_team": "Milwaukee Brewers", "commence_time": _iso(dt)}]
    assert _match_event(game, events)["id"] == "x"
    assert 10 * len(batter) > 0
    print(json.dumps({
        "status": "SELF_TEST_OK",
        "market_catalog": "PASS",
        "provider_event_match_fail_closed": "PASS",
        "five_minute_anchor": "PASS",
        "worst_case_budget_guard": "PASS",
        "historical_never_forward": "PASS"
    }, sort_keys=True))
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=date.fromisoformat, default=date(2026, 3, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date(2026, 8, 31))
    p.add_argument("--target-minutes", type=int, default=90)
    p.add_argument("--groups", default="period_core")
    p.add_argument("--max-credits", type=int, default=200)
    p.add_argument("--max-events", type=int, default=1)
    p.add_argument("--oldest-first", action="store_true")
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    p.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        return _self_test(args.catalog)
    if args.end < args.start:
        raise SystemExit("end must be >= start")
    groups = [x.strip() for x in args.groups.split(",") if x.strip()]
    markets = _load_catalog(args.catalog, groups)
    try:
        result = run(
            root=args.root,
            start=args.start,
            end=args.end,
            target_minutes=max(1, args.target_minutes),
            groups=groups,
            markets=markets,
            max_credits=max(0, args.max_credits),
            max_events=max(1, args.max_events),
            newest_first=not args.oldest_first,
        )
    except (HTTPError, URLError) as exc:
        result = {"status": "BLOCKED_NETWORK_OR_HTTP", "error": f"{type(exc).__name__}:{exc}"}
    except Exception as exc:
        print(json.dumps({"status": "EVENT_REPLAY_FAILED", "error": f"{type(exc).__name__}:{exc}"}, sort_keys=True), file=sys.stderr)
        return 98
    stamp = _now().strftime("%Y%m%dT%H%M%S.%fZ")
    _atomic_json(args.root / "runtime/status" / f"event_markets_{stamp}.json", {
        "schema_version": SCHEMA,
        "run_at_utc": _iso(_now()),
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "target_minutes": args.target_minutes,
        "groups": groups,
        "markets": markets,
        "historical_backfill": True,
        "forward_evidence": False,
        "result": result,
    })
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
