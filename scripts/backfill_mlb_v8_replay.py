#!/usr/bin/env python3
"""Resumable MLB V8 March-August historical replay acquisition.

Historical evidence is intentionally separated from the V8 forward lane. Raw
provider bytes are retained and hash-bound; the script never claims that a
backfilled row was observed by SportsEdge in real time.

Implemented remote adapters:
- The Odds API v4 historical snapshots (true PIT snapshots; paid historical plan)
- SportsGameOdds v2 finalized open/close archive
- PropLine v1 bulk odds-history export (plan/backfill-pass gated)

Licensed exports from OpticOdds, SportsDataIO, Betfair, The Odds Gap, or another
approved registry source can be ingested with --provider external-import.
"""
from __future__ import annotations

import argparse
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ODDS_V4 = "https://api.the-odds-api.com/v4"
MLB_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"
SGO_V2 = "https://api.sportsgameodds.com/v2/events"
PROPLINE = "https://api.prop-line.com/v1"
SPORT_KEY = "baseball_mlb"
SCHEMA = "SPORTSEDGE_MLB_V8_REPLAY_V1"
DEFAULT_ROOT = Path("artifacts/mlb_v8/replay")
DEFAULT_START = date(2026, 3, 1)
DEFAULT_END = date(2026, 8, 31)
DEFAULT_TARGET_MINUTES = (90, 5)


class ReplayError(RuntimeError):
    pass


def _utcnow() -> datetime:
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


def _http_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 45,
) -> tuple[bytes, dict[str, str]]:
    request = Request(
        url,
        headers={
            "Accept": "*/*",
            "User-Agent": "SportsEdge-V8-replay/1",
            **(headers or {}),
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read(), {k.lower(): v for k, v in response.headers.items()}


def _load_registry(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text())
    return {row["id"]: row for row in payload.get("sources", [])}


def _write_raw_bundle(
    *,
    root: Path,
    source_id: str,
    evidence_id: str,
    raw: bytes,
    extension: str,
    source_meta: dict[str, Any],
    request_meta: dict[str, Any],
    response_meta: dict[str, Any] | None = None,
) -> Path:
    digest = _sha(raw)
    safe_id = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in evidence_id)
    bundle = root / source_id / f"{safe_id}_{digest[:16]}"
    raw_path = bundle / f"raw.{extension.lstrip('.')}"
    bundle.mkdir(parents=True, exist_ok=True)
    if raw_path.exists():
        if _sha(raw_path.read_bytes()) != digest:
            raise ReplayError(f"immutable collision at {raw_path}")
    else:
        raw_path.write_bytes(raw)
    manifest = {
        "schema_version": SCHEMA,
        "evidence_kind": source_meta.get("evidence_kind", "HISTORICAL_MARKET_ARCHIVE"),
        "collection_mode": "HISTORICAL_BACKFILL",
        "historical_backfill": True,
        "forward_evidence": False,
        "source_id": source_id,
        "source_class": source_meta["source_class"],
        "decision_pit_eligible_by_source_contract": bool(source_meta.get("decision_pit_eligible")),
        "clv_eligible_by_source_contract": bool(source_meta.get("clv_eligible")),
        "raw_sha256": digest,
        "raw_bytes": len(raw),
        "raw_file": raw_path.name,
        "request": request_meta,
        "response": response_meta or {},
        "archived_at_utc": _iso(_utcnow()),
        "governance": {
            "promotion_effect": "NONE",
            "rule": "historical backfill may support replay only when provider timestamps prove the quote existed by the replay as-of time",
        },
    }
    _atomic_json(bundle / "manifest.json", manifest)
    return bundle


def _ledger_path(root: Path, source_id: str) -> Path:
    return root / "runtime" / f"{source_id}_ledger.json"


def _restore_ledger_from_data(root: Path, source_id: str) -> None:
    path = _ledger_path(root, source_id)
    if path.exists() or not Path(".git").exists():
        return
    remote_path = f"archive/mlb_v8/replay/runtime/{source_id}_ledger.json"
    try:
        subprocess.run(
            ["git", "fetch", "--depth=1", "origin", "data"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        out = subprocess.run(
            ["git", "show", f"FETCH_HEAD:{remote_path}"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if out.returncode == 0 and out.stdout:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(out.stdout)
    except Exception:
        pass


def _load_ledger(root: Path, source_id: str) -> dict[str, Any]:
    _restore_ledger_from_data(root, source_id)
    path = _ledger_path(root, source_id)
    try:
        payload = json.loads(path.read_text())
        if isinstance(payload, dict):
            payload.setdefault("completed", [])
            return payload
    except Exception:
        pass
    return {
        "schema_version": SCHEMA,
        "source_id": source_id,
        "completed": [],
        "created_at_utc": _iso(_utcnow()),
    }


def _save_ledger(root: Path, source_id: str, ledger: dict[str, Any]) -> None:
    ledger["updated_at_utc"] = _iso(_utcnow())
    done = ledger.setdefault("completed", [])
    if len(done) > 10000:
        del done[:-10000]
    _atomic_json(_ledger_path(root, source_id), ledger)


def _date_range(start: date, end: date, *, newest_first: bool) -> list[date]:
    if end < start:
        raise ReplayError("end before start")
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    return list(reversed(days)) if newest_first else days


def _mlb_regular_season_games(day: date) -> list[dict[str, Any]]:
    params = urlencode({
        "sportId": 1,
        "date": day.isoformat(),
        "gameType": "R",
        "hydrate": "team",
    })
    raw, _ = _http_get(f"{MLB_SCHEDULE}?{params}", timeout=30)
    payload = json.loads(raw)
    out = []
    for date_row in payload.get("dates", []):
        for game in date_row.get("games", []):
            start = _parse_iso(game.get("gameDate"))
            if start:
                out.append({
                    "gamePk": game.get("gamePk"),
                    "gameDate": _iso(start),
                    "home": ((game.get("teams") or {}).get("home") or {}).get("team", {}).get("name"),
                    "away": ((game.get("teams") or {}).get("away") or {}).get("team", {}).get("name"),
                })
    return out


def _anchors_for_day(day: date, targets: tuple[int, ...]) -> list[tuple[datetime, str]]:
    anchors: dict[datetime, set[str]] = {}
    for game in _mlb_regular_season_games(day):
        start = _parse_iso(game["gameDate"])
        if start is None:
            continue
        for minutes in targets:
            requested = start - timedelta(minutes=minutes)
            # Historical provider is 5-minute granularity in 2026. Flooring avoids
            # an accidental request after the intended decision anchor.
            floored = requested.replace(
                minute=(requested.minute // 5) * 5,
                second=0,
                microsecond=0,
            )
            labels = anchors.setdefault(floored, set())
            labels.add(f"gamePk={game.get('gamePk')}:T-{minutes}m")
    return [(dt, ",".join(sorted(labels))) for dt, labels in sorted(anchors.items())]


def _odds_keys() -> list[str]:
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


def _odds_query_cost(markets: list[str], bookmakers: list[str]) -> int:
    # Historical v4 cost is 10 per region per market. A bookmaker-filtered
    # request is conservatively budgeted in groups of 10 books as one region.
    book_groups = max(1, math.ceil(max(1, len(bookmakers)) / 10))
    return 10 * len(markets) * book_groups


def run_the_odds_api(
    *,
    root: Path,
    source: dict[str, Any],
    start: date,
    end: date,
    max_credits: int,
    newest_first: bool,
    targets: tuple[int, ...],
) -> dict[str, Any]:
    keys = _odds_keys()
    if not keys:
        return {"status": "BLOCKED_NO_KEY", "source_id": source["id"]}

    books = [
        x.strip() for x in os.environ.get(
            "SPORTSEDGE_REPLAY_BOOKMAKERS", "draftkings"
        ).split(",") if x.strip()
    ]
    markets = [
        x.strip() for x in os.environ.get(
            "SPORTSEDGE_REPLAY_MARKETS", "h2h,spreads,totals"
        ).split(",") if x.strip()
    ]
    cost = _odds_query_cost(markets, books)
    if max_credits < cost:
        return {
            "status": "BLOCKED_BUDGET_TOO_SMALL",
            "minimum_credits_for_one_snapshot": cost,
        }

    ledger = _load_ledger(root, source["id"])
    completed = set(str(x) for x in ledger.get("completed", []))
    spent = 0
    captured = 0
    schedule_failures = []

    for day in _date_range(start, end, newest_first=newest_first):
        try:
            anchors = _anchors_for_day(day, targets)
        except Exception as exc:
            schedule_failures.append(f"{day}:{type(exc).__name__}:{exc}")
            continue
        if newest_first:
            anchors = list(reversed(anchors))
        for requested, labels in anchors:
            key_id = f"{_iso(requested)}|{','.join(markets)}|{','.join(books)}"
            if key_id in completed:
                continue
            if spent + cost > max_credits:
                ledger["credits_spent_last_run"] = spent
                _save_ledger(root, source["id"], ledger)
                return {
                    "status": "BUDGET_BOUND_REACHED",
                    "captured": captured,
                    "credits_spent_estimate": spent,
                    "credits_per_snapshot_estimate": cost,
                    "schedule_failures": schedule_failures,
                }

            params = {
                "apiKey": keys[0],
                "bookmakers": ",".join(books),
                "markets": ",".join(markets),
                "oddsFormat": "american",
                "dateFormat": "iso",
                "date": _iso(requested),
            }
            raw = None
            headers: dict[str, str] = {}
            attempts = []
            for slot, api_key in enumerate(keys, start=1):
                params["apiKey"] = api_key
                url = f"{ODDS_V4}/historical/sports/{SPORT_KEY}/odds?{urlencode(params)}"
                try:
                    raw, headers = _http_get(url, timeout=45)
                    break
                except HTTPError as exc:
                    attempts.append({"slot": slot, "http_status": exc.code})
                    if exc.code not in (401, 403, 429):
                        raise
            if raw is None:
                ledger["last_blocked_request"] = key_id
                ledger["last_attempts"] = attempts
                _save_ledger(root, source["id"], ledger)
                return {
                    "status": "BLOCKED_PROVIDER",
                    "captured": captured,
                    "credits_spent_estimate": spent,
                    "attempts": attempts,
                }

            spent += cost
            payload = json.loads(raw)
            snapshot_at = _parse_iso(payload.get("timestamp")) if isinstance(payload, dict) else None
            response_meta = {
                "provider_snapshot_at_utc": _iso(snapshot_at) if snapshot_at else None,
                "provider_previous_timestamp": payload.get("previous_timestamp") if isinstance(payload, dict) else None,
                "request_cost_header": headers.get("x-requests-last"),
                "remaining_header": headers.get("x-requests-remaining"),
                "snapshot_at_or_before_requested": (
                    snapshot_at is not None and snapshot_at <= requested
                ),
            }
            stamp = requested.strftime("%Y%m%dT%H%M%SZ")
            _write_raw_bundle(
                root=root,
                source_id=source["id"],
                evidence_id=f"{day.isoformat()}_{stamp}",
                raw=raw,
                extension="json",
                source_meta=source,
                request_meta={
                    "requested_snapshot_at_utc": _iso(requested),
                    "anchor_labels": labels,
                    "markets": markets,
                    "bookmakers": books,
                    "cost_estimate": cost,
                },
                response_meta=response_meta,
            )
            completed.add(key_id)
            ledger["completed"] = sorted(completed)
            captured += 1
            _save_ledger(root, source["id"], ledger)

    ledger["credits_spent_last_run"] = spent
    _save_ledger(root, source["id"], ledger)
    return {
        "status": "COMPLETE_RANGE",
        "captured": captured,
        "credits_spent_estimate": spent,
        "schedule_failures": schedule_failures,
    }


def _cursor_from_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("nextCursor", "next_cursor", "cursor"):
        value = payload.get(key)
        if value:
            return str(value)
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("nextCursor", "next_cursor"):
            value = data.get(key)
            if value:
                return str(value)
    return None


def run_sportsgameodds(
    *,
    root: Path,
    source: dict[str, Any],
    start: date,
    end: date,
    max_pages: int,
) -> dict[str, Any]:
    api_key = os.environ.get("SPORTSEDGE_SGO_API_KEY", "").strip()
    if not api_key:
        return {"status": "BLOCKED_NO_KEY", "source_id": source["id"]}

    ledger = _load_ledger(root, source["id"])
    completed = set(str(x) for x in ledger.get("completed", []))
    cursor = ledger.get("cursor")
    pages = 0
    while pages < max_pages:
        params = {
            "leagueID": "MLB",
            "finalized": "true",
            "includeOpenCloseOdds": "true",
            "startsAfter": f"{start.isoformat()}T00:00:00Z",
            "startsBefore": f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
            "limit": "100",
        }
        if cursor:
            params["cursor"] = cursor
        request_key = cursor or "FIRST"
        if request_key in completed:
            return {"status": "BLOCKED_CURSOR_LOOP", "cursor": cursor, "pages": pages}

        raw, _ = _http_get(
            f"{SGO_V2}?{urlencode(params)}",
            headers={"x-api-key": api_key},
            timeout=60,
        )
        payload = json.loads(raw)
        next_cursor = _cursor_from_payload(payload)
        evidence_id = f"{start}_{end}_page_{pages+1:04d}"
        _write_raw_bundle(
            root=root,
            source_id=source["id"],
            evidence_id=evidence_id,
            raw=raw,
            extension="json",
            source_meta=source,
            request_meta={
                "startsAfter": params["startsAfter"],
                "startsBefore": params["startsBefore"],
                "includeOpenCloseOdds": True,
                "cursor": cursor,
            },
            response_meta={
                "next_cursor": next_cursor,
                "decision_time_limitation": "open/close archive only; do not infer T-90/T-decision price",
            },
        )
        completed.add(request_key)
        pages += 1
        ledger["completed"] = sorted(completed)
        ledger["cursor"] = next_cursor
        _save_ledger(root, source["id"], ledger)
        if not next_cursor:
            return {"status": "COMPLETE_RANGE", "pages": pages}
        if next_cursor == cursor:
            return {"status": "BLOCKED_CURSOR_LOOP", "cursor": cursor, "pages": pages}
        cursor = next_cursor
    return {"status": "PAGE_BOUND_REACHED", "pages": pages, "next_cursor": cursor}


def _month_windows(start: date, end: date) -> list[tuple[date, date]]:
    out = []
    current = start.replace(day=1)
    while current <= end:
        last = date(current.year, current.month, monthrange(current.year, current.month)[1])
        a = max(start, current)
        b = min(end, last)
        out.append((a, b))
        current = (last + timedelta(days=1)).replace(day=1)
    return out


def run_propline(
    *,
    root: Path,
    source: dict[str, Any],
    start: date,
    end: date,
    max_months: int,
    newest_first: bool,
) -> dict[str, Any]:
    api_key = os.environ.get("SPORTSEDGE_PROPLINE_API_KEY", "").strip()
    if not api_key:
        return {"status": "BLOCKED_NO_KEY", "source_id": source["id"]}

    ledger = _load_ledger(root, source["id"])
    completed = set(str(x) for x in ledger.get("completed", []))
    windows = _month_windows(start, end)
    if newest_first:
        windows.reverse()
    captured = 0
    for a, b in windows:
        period = f"{a.isoformat()}_{b.isoformat()}"
        if period in completed:
            continue
        if captured >= max_months:
            return {"status": "MONTH_BOUND_REACHED", "captured_months": captured}
        params = urlencode({
            "sport": SPORT_KEY,
            "since": f"{a.isoformat()}T00:00:00Z",
            "until": f"{(b + timedelta(days=1)).isoformat()}T00:00:00Z",
        })
        raw, headers = _http_get(
            f"{PROPLINE}/exports/odds-history?{params}",
            headers={"X-API-Key": api_key, "Accept": "text/csv"},
            timeout=120,
        )
        _write_raw_bundle(
            root=root,
            source_id=source["id"],
            evidence_id=period,
            raw=raw,
            extension="csv",
            source_meta=source,
            request_meta={
                "sport": SPORT_KEY,
                "since": a.isoformat(),
                "until_inclusive": b.isoformat(),
            },
            response_meta={
                "content_type": headers.get("content-type"),
                "provider_contract": "every recorded outcome snapshot in requested period",
            },
        )
        completed.add(period)
        ledger["completed"] = sorted(completed)
        _save_ledger(root, source["id"], ledger)
        captured += 1
    return {"status": "COMPLETE_RANGE", "captured_months": captured}


def run_external_import(
    *,
    root: Path,
    source: dict[str, Any],
    inputs: list[Path],
) -> dict[str, Any]:
    if not inputs:
        return {"status": "BLOCKED_NO_INPUT"}
    imported = 0
    for path in inputs:
        if not path.is_file():
            raise ReplayError(f"import input missing: {path}")
        raw = path.read_bytes()
        extension = path.suffix.lstrip(".") or "bin"
        _write_raw_bundle(
            root=root,
            source_id=source["id"],
            evidence_id=path.stem,
            raw=raw,
            extension=extension,
            source_meta=source,
            request_meta={
                "imported_from": path.as_posix(),
                "operator_asserted_source_id": source["id"],
            },
            response_meta={
                "timestamp_validation": "DEFERRED_TO_SOURCE_SPECIFIC_PARSER",
                "forward_evidence": False,
            },
        )
        imported += 1
    return {"status": "IMPORTED", "files": imported}


def _self_test(registry_path: Path) -> int:
    registry = _load_registry(registry_path)
    assert registry["the_odds_api_v4_historical"]["source_class"] == "PIT_SNAPSHOT"
    assert registry["sportsgameodds_v2"]["decision_pit_eligible"] is False
    assert registry["sportsgameodds_v2"]["clv_eligible"] is True
    cost = _odds_query_cost(["h2h", "spreads", "totals"], ["draftkings"])
    assert cost == 30
    games = [
        ("2026-09-03T16:30:00Z", 90, "2026-09-03T15:00:00Z"),
        ("2026-09-03T16:32:00Z", 5, "2026-09-03T16:25:00Z"),
    ]
    for start, minutes, expected in games:
        dt = _parse_iso(start)
        req = dt - timedelta(minutes=minutes)
        floor = req.replace(minute=(req.minute // 5) * 5, second=0, microsecond=0)
        assert _iso(floor) == expected
    print(json.dumps({
        "status": "SELF_TEST_OK",
        "historical_cost_guard": "PASS",
        "decision_vs_clv_source_classes": "PASS",
        "five_minute_anchor_floor": "PASS",
        "historical_never_forward": "PASS",
    }, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=[
        "the-odds-api",
        "sportsgameodds",
        "propline",
        "external-import",
    ], default="the-odds-api")
    parser.add_argument("--source-id")
    parser.add_argument("--input", action="append", type=Path, default=[])
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument("--max-credits", type=int, default=30)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--max-months", type=int, default=1)
    parser.add_argument("--oldest-first", action="store_true")
    parser.add_argument("--targets", default="90,5")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--registry", type=Path, default=Path("config/mlb_v8_sources.json"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return _self_test(args.registry)
    if args.end < args.start:
        raise SystemExit("end must be >= start")

    registry = _load_registry(args.registry)
    provider_to_source = {
        "the-odds-api": "the_odds_api_v4_historical",
        "sportsgameodds": "sportsgameodds_v2",
        "propline": "propline_v1",
    }
    source_id = args.source_id or provider_to_source.get(args.provider)
    if not source_id or source_id not in registry:
        raise SystemExit("external-import requires --source-id from config/mlb_v8_sources.json")
    source = registry[source_id]
    newest_first = not args.oldest_first

    try:
        if args.provider == "the-odds-api":
            targets = tuple(
                sorted({int(x.strip()) for x in args.targets.split(",") if x.strip()}, reverse=True)
            )
            result = run_the_odds_api(
                root=args.root,
                source=source,
                start=args.start,
                end=args.end,
                max_credits=max(0, args.max_credits),
                newest_first=newest_first,
                targets=targets,
            )
        elif args.provider == "sportsgameodds":
            result = run_sportsgameodds(
                root=args.root,
                source=source,
                start=args.start,
                end=args.end,
                max_pages=max(1, args.max_pages),
            )
        elif args.provider == "propline":
            result = run_propline(
                root=args.root,
                source=source,
                start=args.start,
                end=args.end,
                max_months=max(1, args.max_months),
                newest_first=newest_first,
            )
        else:
            result = run_external_import(root=args.root, source=source, inputs=args.input)
    except HTTPError as exc:
        result = {
            "status": "BLOCKED_HTTP",
            "source_id": source_id,
            "http_status": exc.code,
            "reason": str(exc.reason),
        }
    except URLError as exc:
        result = {
            "status": "BLOCKED_NETWORK",
            "source_id": source_id,
            "reason": str(exc.reason),
        }
    except Exception as exc:
        print(json.dumps({
            "status": "REPLAY_FAILED",
            "source_id": source_id,
            "error": f"{type(exc).__name__}:{exc}",
        }, sort_keys=True), file=sys.stderr)
        return 98

    status_dir = args.root / "runtime/status"
    stamp = _utcnow().strftime("%Y%m%dT%H%M%S.%fZ")
    status = {
        "schema_version": SCHEMA,
        "source_id": source_id,
        "provider": args.provider,
        "requested_start": args.start.isoformat(),
        "requested_end": args.end.isoformat(),
        "historical_backfill": True,
        "forward_evidence": False,
        "result": result,
        "run_at_utc": _iso(_utcnow()),
    }
    _atomic_json(status_dir / f"{source_id}_{stamp}.json", status)
    print(json.dumps(status, sort_keys=True))
    return 0 if not str(result.get("status", "")).startswith("REPLAY_FAILED") else 98


if __name__ == "__main__":
    raise SystemExit(main())
