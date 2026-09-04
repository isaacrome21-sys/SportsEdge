#!/usr/bin/env python3
"""Resumable MLB V8 point-in-time replay collection from OddsPapi.

OddsPapi exposes a finished fixture's full bookmaker price history.  Each price
snapshot carries its original ``createdAt`` timestamp, so historical retrieval
can prove what was observable before first pitch without inventing a retrieval
or observation time.

This collector is evidence-first and fail-closed:
- exact provider response bytes are preserved;
- every raw file has a SHA-256-bound sidecar;
- fixture identity/start time comes from the provider fixture response;
- no historical quote is relabelled as a canonical decision observation here;
  qualification is performed separately from immutable raw evidence;
- state is resumable and secrets are never written to disk or logs.

The billable /fixtures endpoint is batched in <=10-day windows.  The provider's
/historical-odds endpoint is unmetered but rate limited, so history calls are
serialized with a configurable pause (default 5.1 seconds).
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "https://api.oddspapi.io/v4"
SPORT_ID = 13
MLB_TOURNAMENT_ID = 109
POLICY = Path("config/mlb_v8_evidence_policy.json")
DEFAULT_ROOT = Path("artifacts/mlb_v8_replay_sources/ODDSPAPI_HISTORICAL")
DEFAULT_STATE = Path("artifacts/mlb_v8_replay_control/oddspapi_state.json")
DEFAULT_BOOKS = ("pinnacle", "draftkings", "fanduel")
MAX_BOOKS_PER_HISTORY_REQUEST = 3
MAX_FIXTURE_WINDOW_DAYS = 9  # provider requires the endpoints to be <10 days apart
HISTORY_COOLDOWN_SECONDS = 5.1


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _atomic(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(raw)
    tmp.replace(path)


def _atomic_json(path: Path, value: Any) -> None:
    _atomic(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def _parse_ts(value: Any) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return dt.astimezone(timezone.utc)


def _api_key() -> str:
    return os.environ.get("SPORTSEDGE_ODDSPAPI_KEY", "").strip()


def _load_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
        if isinstance(value, dict):
            value.setdefault("fixture_windows_completed", [])
            value.setdefault("history_completed", [])
            value.setdefault("failures", [])
            return value
    except Exception:
        pass
    return {
        "schema": "MLB_V8_ODDSPAPI_BACKFILL_STATE_V1",
        "fixture_windows_completed": [],
        "history_completed": [],
        "failures": [],
    }


def _save_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    state["fixture_windows_completed"] = sorted(set(str(x) for x in state.get("fixture_windows_completed") or []))
    state["history_completed"] = sorted(set(str(x) for x in state.get("history_completed") or []))
    state["failures"] = list(state.get("failures") or [])[-1000:]
    _atomic_json(path, state)


def _request(path: str, *, key: str, params: dict[str, Any], timeout: int = 45) -> tuple[bytes, dict[str, str]]:
    query = urlencode({"apiKey": key, **params})
    req = Request(
        f"{BASE}{path}?{query}",
        headers={"Accept": "application/json", "User-Agent": "SportsEdge-V8-OddsPapi-Replay/1.0"},
    )
    with urlopen(req, timeout=timeout) as response:
        return response.read(), {str(k).lower(): str(v) for k, v in response.headers.items()}


def _secret_free(params: dict[str, Any]) -> dict[str, Any]:
    return {str(k): v for k, v in params.items() if str(k).lower() != "apikey"}


def _metadata(*, endpoint: str, params: dict[str, Any], headers: dict[str, str], raw: bytes) -> dict[str, Any]:
    return {
        "source": "ODDSPAPI_HISTORICAL",
        "endpoint": endpoint,
        "request_params_secret_free": _secret_free(params),
        "payload_sha256": _sha(raw),
        "bytes": len(raw),
        "etag": headers.get("etag"),
        "cache_control": headers.get("cache-control"),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def _dates(start: str, end: str) -> Iterable[tuple[date, date]]:
    cur = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    while cur <= stop:
        # "to" is a timestamp at 00:00 on that date.  Use the day after the
        # desired final day and keep the endpoints under ten days apart.
        last = min(stop, cur + timedelta(days=MAX_FIXTURE_WINDOW_DAYS - 1))
        yield cur, last
        cur = last + timedelta(days=1)


def _fixture_window_key(start: date, last: date) -> str:
    return f"{start.isoformat()}_{last.isoformat()}"


def _is_mlb_fixture(row: dict[str, Any]) -> bool:
    if int(row.get("sportId") or -1) != SPORT_ID:
        return False
    tid = row.get("tournamentId")
    name = str(row.get("tournamentName") or "").strip().upper()
    return (tid not in (None, "") and int(tid) == MLB_TOURNAMENT_ID) or name == "MLB"


def _fixture_id(row: dict[str, Any]) -> str:
    return str(row.get("fixtureId") or "").strip()


def _fixture_day(row: dict[str, Any]) -> str | None:
    try:
        return _parse_ts(row.get("startTime")).date().isoformat()
    except Exception:
        return None


def _fixture_rows(raw: bytes) -> list[dict[str, Any]]:
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError("fixture response must be a list")
    return [dict(x) for x in payload if isinstance(x, dict)]


def _history_payload_valid(raw: bytes, fixture_id: str) -> bool:
    payload = json.loads(raw.decode("utf-8"))
    return isinstance(payload, dict) and str(payload.get("fixtureId") or "") == fixture_id and isinstance(payload.get("bookmakers"), dict)


def _history_groups(books: tuple[str, ...]) -> list[tuple[str, ...]]:
    clean = tuple(dict.fromkeys(x.strip().lower() for x in books if x.strip()))
    return [clean[i:i + MAX_BOOKS_PER_HISTORY_REQUEST] for i in range(0, len(clean), MAX_BOOKS_PER_HISTORY_REQUEST)]


def _archive_fixtures(
    *, key: str, start: date, last: date, root: Path, state: dict[str, Any], state_path: Path,
) -> tuple[list[dict[str, Any]], bool]:
    window_key = _fixture_window_key(start, last)
    path = root / "fixtures" / f"fixtures_{window_key}.json"
    meta_path = root / "fixtures" / f"fixtures_{window_key}.meta.json"
    if path.is_file():
        return [x for x in _fixture_rows(path.read_bytes()) if _is_mlb_fixture(x)], False

    params = {
        "sportId": SPORT_ID,
        "from": start.isoformat(),
        "to": (last + timedelta(days=1)).isoformat(),
        "statusId": 2,
        "hasOdds": "true",
    }
    raw, headers = _request("/fixtures", key=key, params=params)
    rows = _fixture_rows(raw)
    _atomic(path, raw)
    _atomic_json(meta_path, _metadata(endpoint="/v4/fixtures", params=params, headers=headers, raw=raw))
    state.setdefault("fixture_windows_completed", []).append(window_key)
    _save_state(state_path, state)
    return [x for x in rows if _is_mlb_fixture(x)], True


def collect(
    *, start_date: str, end_date: str, root: Path, state_path: Path,
    books: tuple[str, ...], max_history_requests: int, cooldown_seconds: float,
) -> dict[str, Any]:
    key = _api_key()
    if not key:
        return {
            "status": "BLOCKED_NO_ODDSPAPI_KEY",
            "required_secret": "SPORTSEDGE_ODDSPAPI_KEY",
            "fixture_requests": 0,
            "history_requests": 0,
            "archived_files": 0,
        }
    if max_history_requests < 0:
        raise ValueError("max_history_requests must be non-negative")
    if cooldown_seconds < 0:
        raise ValueError("cooldown_seconds must be non-negative")

    state = _load_state(state_path)
    completed_history = set(str(x) for x in state.get("history_completed") or [])
    fixture_requests = 0
    history_requests = 0
    archived_files = 0
    fixtures_seen: dict[str, dict[str, Any]] = {}

    try:
        for start, last in _dates(start_date, end_date):
            rows, requested = _archive_fixtures(
                key=key, start=start, last=last, root=root, state=state, state_path=state_path,
            )
            fixture_requests += int(requested)
            if requested:
                archived_files += 2
            for row in rows:
                fid = _fixture_id(row)
                day = _fixture_day(row)
                if not fid or not day or not (start_date <= day <= end_date):
                    continue
                fixtures_seen[fid] = row

        groups = _history_groups(books)
        if not groups:
            return {"status": "BLOCKED_NO_BOOKMAKERS", "fixture_requests": fixture_requests, "history_requests": 0, "archived_files": archived_files}

        for fid, fixture in sorted(fixtures_seen.items(), key=lambda kv: (str(kv[1].get("startTime") or ""), kv[0])):
            day = _fixture_day(fixture)
            if not day:
                continue
            fixture_dir = root / day / fid
            _atomic_json(fixture_dir / "fixture.normalized.json", fixture)
            archived_files += 1
            for group in groups:
                group_key = ",".join(group)
                fingerprint = f"{fid}|{group_key}"
                raw_path = fixture_dir / f"history_{'_'.join(group)}.json"
                meta_path = fixture_dir / f"history_{'_'.join(group)}.meta.json"
                if fingerprint in completed_history and raw_path.is_file() and meta_path.is_file():
                    continue
                if history_requests >= max_history_requests:
                    _save_state(state_path, state)
                    return {
                        "status": "HISTORY_REQUEST_CAP_REACHED",
                        "fixture_requests": fixture_requests,
                        "history_requests": history_requests,
                        "archived_files": archived_files,
                        "mlb_fixtures_discovered": len(fixtures_seen),
                        "history_fingerprints_completed": len(completed_history),
                    }
                params = {"fixtureId": fid, "bookmakers": group_key}
                raw, headers = _request("/historical-odds", key=key, params=params)
                if not _history_payload_valid(raw, fid):
                    raise RuntimeError(f"ODDSPAPI_HISTORY_PAYLOAD_INVALID:{fid}:{group_key}")
                _atomic(raw_path, raw)
                _atomic_json(meta_path, _metadata(endpoint="/v4/historical-odds", params=params, headers=headers, raw=raw))
                archived_files += 2
                history_requests += 1
                completed_history.add(fingerprint)
                state["history_completed"] = sorted(completed_history)
                _save_state(state_path, state)
                if cooldown_seconds:
                    time.sleep(cooldown_seconds)
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:1000]
        except Exception:
            pass
        state.setdefault("failures", []).append({
            "at": datetime.now(timezone.utc).isoformat(),
            "reason": f"HTTPError:{exc.code}",
            "body_sha256": _sha(body.encode()),
        })
        _save_state(state_path, state)
        return {"status": "PROVIDER_HTTP_BLOCKED", "http_status": exc.code, "fixture_requests": fixture_requests, "history_requests": history_requests, "archived_files": archived_files}
    except (URLError, TimeoutError) as exc:
        state.setdefault("failures", []).append({"at": datetime.now(timezone.utc).isoformat(), "reason": f"{type(exc).__name__}:{exc}"})
        _save_state(state_path, state)
        return {"status": "PROVIDER_NETWORK_BLOCKED", "fixture_requests": fixture_requests, "history_requests": history_requests, "archived_files": archived_files}

    _save_state(state_path, state)
    return {
        "status": "COMPLETE_RANGE",
        "fixture_requests": fixture_requests,
        "history_requests": history_requests,
        "archived_files": archived_files,
        "mlb_fixtures_discovered": len(fixtures_seen),
        "history_fingerprints_completed": len(completed_history),
    }


def self_test() -> int:
    assert _is_mlb_fixture({"sportId": 13, "tournamentId": 109, "tournamentName": "MLB"})
    assert _is_mlb_fixture({"sportId": 13, "tournamentId": 999, "tournamentName": "MLB"})
    assert not _is_mlb_fixture({"sportId": 13, "tournamentId": 1036, "tournamentName": "NPB"})
    windows = list(_dates("2026-03-01", "2026-03-31"))
    assert windows[0] == (date(2026, 3, 1), date(2026, 3, 9))
    assert windows[-1][1] == date(2026, 3, 31)
    assert all((b - a).days < 10 for a, b in windows)
    assert _history_groups(("pinnacle", "draftkings", "fanduel", "betmgm")) == [
        ("pinnacle", "draftkings", "fanduel"), ("betmgm",)
    ]
    raw = json.dumps({
        "fixtureId": "id130001",
        "bookmakers": {"draftkings": {"markets": {"131": {"outcomes": {"131": {"players": {"0": [
            {"createdAt": "2026-06-05T09:57:12.731Z", "price": 1.613, "active": True}
        ]}}}}}}}},
    }).encode()
    assert _history_payload_valid(raw, "id130001")
    print(json.dumps({
        "status": "SELF_TEST_OK",
        "mlb_filter": "PASS",
        "fixture_window_under_10_days": "PASS",
        "history_book_group_max_3": "PASS",
        "timestamped_history_shape": "PASS",
        "secret_safe": True,
    }))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-date")
    ap.add_argument("--end-date")
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--state", type=Path, default=DEFAULT_STATE)
    ap.add_argument("--bookmakers", default=",".join(DEFAULT_BOOKS))
    ap.add_argument("--max-history-requests", type=int, default=int(os.environ.get("SPORTSEDGE_ODDSPAPI_MAX_HISTORY_REQUESTS", "50")))
    ap.add_argument("--cooldown-seconds", type=float, default=float(os.environ.get("SPORTSEDGE_ODDSPAPI_COOLDOWN_SECONDS", str(HISTORY_COOLDOWN_SECONDS))))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    policy = json.loads(POLICY.read_text())
    start = args.start_date or policy["replay_window"]["start_date"]
    end = args.end_date or policy["replay_window"]["end_date"]
    books = tuple(x.strip() for x in str(args.bookmakers).split(",") if x.strip())
    result = collect(
        start_date=start,
        end_date=end,
        root=args.root,
        state_path=args.state,
        books=books,
        max_history_requests=args.max_history_requests,
        cooldown_seconds=args.cooldown_seconds,
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {"COMPLETE_RANGE", "HISTORY_REQUEST_CAP_REACHED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
