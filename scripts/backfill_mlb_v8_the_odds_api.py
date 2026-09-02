#!/usr/bin/env python3
"""Resumable March-August MLB V8 replay collection from legitimate raw sources.

The collector always archives free MLB StatsAPI schedule/results bytes. When a paid
The Odds API historical entitlement is available, it adds exact historical sportsbook
snapshots. Requests are budget-capped, resumable, keyring-aware, and secret-safe.

Featured game markets are captured at every policy target. Additional/prop markets
are captured at the standardized decision/close targets (T-30 and T0) when provider
event identity can be bound to the MLB schedule. Missing access stays missing.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ODDS_BASE = "https://api.the-odds-api.com/v4"
SPORT_KEY = "baseball_mlb"
MLB_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"
POLICY = Path("config/mlb_v8_evidence_policy.json")
DEFAULT_ROOT = Path("artifacts/mlb_v8_replay_sources")
DEFAULT_STATE = Path("artifacts/mlb_v8_replay_control/the_odds_api_state.json")
FEATURED_MARKETS = ("h2h", "spreads", "totals")
ADDITIONAL_MARKETS = (
    "batter_home_runs", "batter_home_runs_alternate",
    "batter_hits", "batter_hits_alternate",
    "batter_total_bases", "batter_total_bases_alternate",
    "batter_rbis", "batter_rbis_alternate",
    "batter_runs_scored", "batter_runs_scored_alternate",
    "batter_hits_runs_rbis", "batter_hits_runs_rbis_alternate",
    "batter_singles", "batter_singles_alternate",
    "batter_doubles", "batter_doubles_alternate",
    "batter_triples", "batter_triples_alternate",
    "batter_walks", "batter_walks_alternate",
    "batter_strikeouts", "batter_strikeouts_alternate",
    "batter_stolen_bases",
    "pitcher_strikeouts", "pitcher_strikeouts_alternate",
    "pitcher_hits_allowed", "pitcher_hits_allowed_alternate",
    "pitcher_walks", "pitcher_walks_alternate",
    "pitcher_earned_runs", "pitcher_earned_runs_alternate",
    "pitcher_outs", "pitcher_outs_alternate",
    "h2h_1st_5_innings", "spreads_1st_5_innings", "totals_1st_5_innings",
    "totals_1st_1_innings", "batter_first_home_run", "pitcher_record_a_win",
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _parse_ts(value: Any) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return dt.astimezone(timezone.utc)


def _atomic(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(raw)
    tmp.replace(path)


def _atomic_json(path: Path, value: Any) -> None:
    _atomic(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def _keys() -> list[str]:
    values: list[str] = []
    for name in (
        "SPORTSEDGE_ODDS_API_KEY", "SPORTSEDGE_ODDS_API_KEY_2",
        "SPORTSEDGE_ODDS_API_KEY_3", "SPORTSEDGE_ODDS_API_KEY_4",
    ):
        key = os.environ.get(name, "").strip()
        if key and key not in values:
            values.append(key)
    return values


def _load_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
        if isinstance(value, dict):
            value.setdefault("completed", [])
            value.setdefault("failures", [])
            return value
    except Exception:
        pass
    return {"schema": "MLB_V8_THE_ODDS_API_BACKFILL_STATE_V1", "completed": [], "failures": []}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    completed = list(dict.fromkeys(str(x) for x in state.get("completed") or []))
    state["completed"] = completed
    failures = list(state.get("failures") or [])[-500:]
    state["failures"] = failures
    _atomic_json(path, state)


def _request_raw(url: str, *, timeout: int = 30) -> tuple[bytes, dict[str, str]]:
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge-V8-Replay/1.0"})
    with urlopen(req, timeout=timeout) as response:
        return response.read(), {str(k).lower(): str(v) for k, v in response.headers.items()}


def _schedule_raw(day: str) -> bytes:
    url = MLB_SCHEDULE + "?" + urlencode({"sportId": 1, "date": day, "hydrate": "team"})
    raw, _ = _request_raw(url, timeout=20)
    return raw


def _games_from_schedule(raw: bytes) -> list[dict[str, Any]]:
    payload = json.loads(raw.decode("utf-8"))
    games: list[dict[str, Any]] = []
    for date_row in payload.get("dates", []):
        for game in date_row.get("games", []):
            # Replay validation is for the regular MLB model, not spring/exhibition.
            if str(game.get("gameType") or "").upper() != "R":
                continue
            teams = game.get("teams") or {}
            game_pk = game.get("gamePk")
            start = game.get("gameDate")
            if game_pk in (None, "") or not start:
                continue
            games.append({
                "game_id": str(game_pk),
                "first_pitch_at": _parse_ts(start),
                "home_team": str((((teams.get("home") or {}).get("team") or {}).get("name") or "")),
                "away_team": str((((teams.get("away") or {}).get("team") or {}).get("name") or "")),
            })
    return games


def _norm(value: Any) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def _fingerprint(kind: str, **fields: Any) -> str:
    payload = {"kind": kind, **fields}
    return _sha(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode())


def _odds_url(path: str, *, key: str, params: dict[str, Any]) -> str:
    return ODDS_BASE + path + "?" + urlencode({"apiKey": key, **params})


def _provider_fetch(
    *, path: str, params: dict[str, Any], keys: list[str], state: dict[str, Any],
) -> tuple[bytes, dict[str, str], int]:
    attempts: list[dict[str, Any]] = []
    for slot, key in enumerate(keys, start=1):
        try:
            raw, headers = _request_raw(_odds_url(path, key=key, params=params), timeout=40)
            return raw, headers, slot
        except HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            attempts.append({"key_slot": slot, "http_status": exc.code, "body_sha256": _sha(body.encode())})
            if exc.code in {401, 403, 429}:
                continue
            raise
        except URLError as exc:
            attempts.append({"key_slot": slot, "reason": f"URLError:{exc.reason}"})
            continue
    state.setdefault("failures", []).append({
        "at": datetime.now(timezone.utc).isoformat(), "path": path,
        "params": params, "attempts": attempts,
    })
    raise RuntimeError("all historical Odds API key slots failed")


def _metadata(*, source: str, params: dict[str, Any], headers: dict[str, str], key_slot: int, raw: bytes) -> dict[str, Any]:
    return {
        "source": source,
        "request_params_secret_free": params,
        "key_slot": key_slot,
        "payload_sha256": _sha(raw),
        "bytes": len(raw),
        "provider_requests_remaining": headers.get("x-requests-remaining"),
        "provider_requests_used": headers.get("x-requests-used"),
        "provider_request_cost": headers.get("x-requests-last"),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def _provider_events(raw: bytes) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return []
    data = payload.get("data") if isinstance(payload, dict) else payload
    return [dict(x) for x in data if isinstance(x, dict)] if isinstance(data, list) else []


def _bind_events(games: list[dict[str, Any]], events: Iterable[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    event_rows = list(events)
    for game in games:
        candidates: list[tuple[float, str]] = []
        for event in event_rows:
            event_id = str(event.get("id") or "").strip()
            if not event_id:
                continue
            try:
                commence = _parse_ts(event.get("commence_time"))
            except Exception:
                continue
            if _norm(event.get("home_team")) != _norm(game.get("home_team")):
                continue
            if _norm(event.get("away_team")) != _norm(game.get("away_team")):
                continue
            delta = abs((commence - game["first_pitch_at"]).total_seconds())
            if delta <= 90 * 60:
                candidates.append((delta, event_id))
        candidates.sort()
        if len(candidates) == 1 or (len(candidates) > 1 and candidates[0][0] < candidates[1][0]):
            out[str(game["game_id"])] = candidates[0][1]
    return out


def _dates(start: str, end: str):
    current = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    while current <= stop:
        yield current.isoformat()
        current += timedelta(days=1)


def collect(
    *, start_date: str, end_date: str, root: Path, state_path: Path,
    max_requests: int, bookmakers: str, include_additional: bool,
    min_remaining: int,
) -> dict[str, Any]:
    policy = json.loads(POLICY.read_text())
    targets = [int(x) for x in policy["canonical_capture_targets_minutes_before_first_pitch"]]
    keys = _keys()
    state = _load_state(state_path)
    completed = set(str(x) for x in state.get("completed") or [])
    request_count = 0
    archived_files = 0
    blocked_no_key = not bool(keys)
    stop_for_remaining = False

    for day in _dates(start_date, end_date):
        schedule_path = root / "MLB_STATSAPI" / day / "schedule.json"
        if not schedule_path.is_file():
            try:
                raw_schedule = _schedule_raw(day)
                _atomic(schedule_path, raw_schedule)
                archived_files += 1
            except Exception as exc:
                state.setdefault("failures", []).append({"date": day, "source": "MLB_STATSAPI", "reason": f"{type(exc).__name__}:{exc}"})
                _save_state(state_path, state)
                continue
        raw_schedule = schedule_path.read_bytes()
        games = _games_from_schedule(raw_schedule)
        if not games or blocked_no_key or stop_for_remaining:
            continue

        provider_events: list[dict[str, Any]] = []
        requested_times: dict[str, datetime] = {}
        for game in games:
            for target in targets:
                requested = game["first_pitch_at"] - timedelta(minutes=target)
                requested_times[requested.isoformat()] = requested

        for requested_iso, requested in sorted(requested_times.items()):
            fp = _fingerprint("featured", day=day, requested_at=requested_iso, bookmakers=bookmakers)
            if fp in completed:
                # Rehydrate event IDs from prior raw files when available.
                stamp = requested.strftime("%Y%m%dT%H%M%SZ")
                prior = root / "THE_ODDS_API_HISTORICAL" / day / "featured" / f"snapshot_{stamp}.json"
                if prior.is_file():
                    provider_events.extend(_provider_events(prior.read_bytes()))
                continue
            if request_count >= max_requests:
                _save_state(state_path, state)
                return {
                    "status": "REQUEST_CAP_REACHED", "requests_this_run": request_count,
                    "archived_files": archived_files, "blocked_no_key": False,
                }
            params = {
                "regions": "us", "markets": ",".join(FEATURED_MARKETS),
                "oddsFormat": "american", "dateFormat": "iso",
                "bookmakers": bookmakers, "date": requested.isoformat().replace("+00:00", "Z"),
            }
            try:
                raw, headers, slot = _provider_fetch(
                    path=f"/historical/sports/{SPORT_KEY}/odds", params=params, keys=keys, state=state,
                )
            except Exception as exc:
                state.setdefault("failures", []).append({"date": day, "source": "THE_ODDS_API_HISTORICAL", "requested_at": requested_iso, "reason": f"{type(exc).__name__}:{exc}"})
                _save_state(state_path, state)
                return {"status": "PROVIDER_BLOCKED", "requests_this_run": request_count, "archived_files": archived_files}
            request_count += 1
            stamp = requested.strftime("%Y%m%dT%H%M%SZ")
            outdir = root / "THE_ODDS_API_HISTORICAL" / day / "featured"
            _atomic(outdir / f"snapshot_{stamp}.json", raw)
            _atomic_json(outdir / f"snapshot_{stamp}.meta.json", _metadata(source="THE_ODDS_API_HISTORICAL", params=params, headers=headers, key_slot=slot, raw=raw))
            archived_files += 2
            provider_events.extend(_provider_events(raw))
            completed.add(fp); state["completed"] = sorted(completed)
            remaining = headers.get("x-requests-remaining")
            try:
                if remaining is not None and int(remaining) <= int(min_remaining):
                    stop_for_remaining = True
            except ValueError:
                pass
            _save_state(state_path, state)
            if stop_for_remaining:
                break

        if not include_additional or stop_for_remaining:
            continue
        event_map = _bind_events(games, provider_events)
        for game in games:
            event_id = event_map.get(str(game["game_id"]))
            if not event_id:
                state.setdefault("failures", []).append({"date": day, "game_id": game["game_id"], "source": "THE_ODDS_API_HISTORICAL_EVENT", "reason": "PROVIDER_EVENT_ID_UNRESOLVED"})
                continue
            for target in (30, 0):
                requested = game["first_pitch_at"] - timedelta(minutes=target)
                requested_iso = requested.isoformat()
                fp = _fingerprint("additional", day=day, game_id=game["game_id"], event_id=event_id, requested_at=requested_iso, bookmakers=bookmakers)
                if fp in completed:
                    continue
                if request_count >= max_requests:
                    _save_state(state_path, state)
                    return {"status": "REQUEST_CAP_REACHED", "requests_this_run": request_count, "archived_files": archived_files, "blocked_no_key": False}
                params = {
                    "regions": "us", "markets": ",".join(ADDITIONAL_MARKETS),
                    "oddsFormat": "american", "dateFormat": "iso",
                    "bookmakers": bookmakers, "date": requested.isoformat().replace("+00:00", "Z"),
                }
                try:
                    raw, headers, slot = _provider_fetch(
                        path=f"/historical/sports/{SPORT_KEY}/events/{event_id}/odds",
                        params=params, keys=keys, state=state,
                    )
                except Exception as exc:
                    state.setdefault("failures", []).append({"date": day, "game_id": game["game_id"], "source": "THE_ODDS_API_HISTORICAL_EVENT", "requested_at": requested_iso, "reason": f"{type(exc).__name__}:{exc}"})
                    _save_state(state_path, state)
                    return {"status": "PROVIDER_BLOCKED", "requests_this_run": request_count, "archived_files": archived_files}
                request_count += 1
                label = f"Tminus{target}" if target else "T0"
                outdir = root / "THE_ODDS_API_HISTORICAL" / day / "additional" / str(game["game_id"])
                _atomic(outdir / f"{label}.json", raw)
                _atomic_json(outdir / f"{label}.meta.json", _metadata(source="THE_ODDS_API_HISTORICAL_EVENT", params=params, headers=headers, key_slot=slot, raw=raw))
                archived_files += 2
                completed.add(fp); state["completed"] = sorted(completed)
                remaining = headers.get("x-requests-remaining")
                try:
                    if remaining is not None and int(remaining) <= int(min_remaining):
                        stop_for_remaining = True
                except ValueError:
                    pass
                _save_state(state_path, state)
                if stop_for_remaining:
                    break
            if stop_for_remaining:
                break

    _save_state(state_path, state)
    return {
        "status": "COMPLETE_RANGE" if not stop_for_remaining else "STOPPED_PROVIDER_RESERVE",
        "requests_this_run": request_count,
        "archived_files": archived_files,
        "blocked_no_key": blocked_no_key,
        "completed_request_fingerprints": len(completed),
    }


def self_test() -> int:
    raw = json.dumps({"dates": [{"games": [
        {"gamePk": 1, "gameType": "R", "gameDate": "2026-04-01T23:05:00Z", "teams": {"home": {"team": {"name": "Chicago Cubs"}}, "away": {"team": {"name": "New York Mets"}}}},
        {"gamePk": 2, "gameType": "S", "gameDate": "2026-04-01T20:05:00Z", "teams": {"home": {"team": {"name": "A"}}, "away": {"team": {"name": "B"}}}},
    ]}]}).encode()
    games = _games_from_schedule(raw)
    assert len(games) == 1 and games[0]["game_id"] == "1"
    events = [{"id": "evt", "commence_time": "2026-04-01T23:05:00Z", "home_team": "Chicago Cubs", "away_team": "New York Mets"}]
    assert _bind_events(games, events) == {"1": "evt"}
    assert len(ADDITIONAL_MARKETS) >= 30
    assert _fingerprint("x", a=1) == _fingerprint("x", a=1)
    print(json.dumps({"status": "SELF_TEST_OK", "regular_season_filter": "PASS", "event_binding": "PASS", "secret_safe_resume_fingerprint": "PASS"}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--max-requests", type=int, default=int(os.environ.get("SPORTSEDGE_V8_BACKFILL_MAX_REQUESTS", "50")))
    parser.add_argument("--bookmakers", default=os.environ.get("SPORTSEDGE_ODDS_BOOKMAKERS", "draftkings"))
    parser.add_argument("--include-additional", action="store_true")
    parser.add_argument("--min-remaining", type=int, default=int(os.environ.get("SPORTSEDGE_V8_BACKFILL_MIN_REMAINING", "100")))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    policy = json.loads(POLICY.read_text())
    start = args.start_date or policy["replay_window"]["start_date"]
    end = args.end_date or policy["replay_window"]["end_date"]
    if args.max_requests < 0:
        parser.error("--max-requests must be non-negative")
    result = collect(
        start_date=start, end_date=end, root=args.root, state_path=args.state,
        max_requests=args.max_requests, bookmakers=str(args.bookmakers),
        include_additional=bool(args.include_additional), min_remaining=args.min_remaining,
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {"COMPLETE_RANGE", "REQUEST_CAP_REACHED", "STOPPED_PROVIDER_RESERVE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
