#!/usr/bin/env python3
"""Prospective raw market capture for CFB_FORWARD_CLV_POLICY_V1.

Raw captures are NOT evidence by themselves. This script never creates Model_P,
never admits Layer B, never backfills, and never captures after kickoff.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

UTC = timezone.utc
CT = ZoneInfo("America/Chicago")
API_ROOT = "https://api.the-odds-api.com/v4"
SPORT_KEY = "americanfootball_ncaaf"
BOOK = "draftkings"
MAIN_MARKETS = ("h2h", "spreads", "totals")
CLOSE_MARKETS = ("h2h", "spreads", "totals", "alternate_spreads", "alternate_totals")
DEFAULT_POLICY = "config/cfb_forward_clv_policy_v1.json"
KEY_VARS = (
    "SPORTSEDGE_ODDS_API_KEY",
    "SPORTSEDGE_ODDS_API_KEY_2",
    "SPORTSEDGE_ODDS_API_KEY_3",
    "SPORTSEDGE_ODDS_API_KEY_4",
)


class CaptureError(RuntimeError):
    pass


def parse_ts(value: Any) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CaptureError("CFB_FORWARD_TIMESTAMP_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CaptureError("CFB_FORWARD_TIMESTAMP_TIMEZONE_REQUIRED")
    return out.astimezone(UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_policy(path: Path) -> dict[str, Any]:
    p = json.loads(path.read_text(encoding="utf-8"))
    if p.get("policy_id") != "CFB_FORWARD_CLV_POLICY_V1" or p.get("status") != "FROZEN":
        raise CaptureError("CFB_FORWARD_POLICY_NOT_FROZEN")
    adm = p.get("row_admissibility") or {}
    if adm.get("model_p_required") is not True or adm.get("layer_b_rows_prohibited") is not True:
        raise CaptureError("CFB_FORWARD_ADMISSIBILITY_WEAKENED")
    if adm.get("backfill_prohibited") is not True:
        raise CaptureError("CFB_FORWARD_BACKFILL_NOT_PROHIBITED")
    clv = p.get("clv_definition") or {}
    if clv.get("basis") != "EXACT_ORIGINAL_CONTRACT" or clv.get("alternate_line_capture_required") is not True:
        raise CaptureError("CFB_FORWARD_EXACT_CONTRACT_REQUIRED")
    if clv.get("normal_approx_v1", {}).get("permitted_for_promotion_evidence") is not False:
        raise CaptureError("CFB_FORWARD_NORMAL_APPROX_MUST_NOT_BE_EVIDENCE")
    if (p.get("quote_hygiene") or {}).get("book_limit_status_required") is not True:
        raise CaptureError("CFB_FORWARD_LIMIT_STATUS_REQUIREMENT_MISSING")
    return p


def api_keys() -> list[str]:
    return [v for name in KEY_VARS if (v := str(os.environ.get(name) or "").strip())]


def default_opener(req: urllib.request.Request, timeout: int = 30):
    return urllib.request.urlopen(req, timeout=timeout)


def get_json(build_url: Callable[[str], str], keys: Iterable[str], opener: Callable[..., Any]) -> dict[str, Any]:
    failures = []
    for slot, key in enumerate(keys, 1):
        req = urllib.request.Request(build_url(key), headers={"User-Agent": "sportsedge-cfb-forward-clv"})
        try:
            with opener(req, timeout=30) as resp:
                raw = resp.read()
                return {
                    "payload": json.loads(raw),
                    "raw_sha256": sha256_bytes(raw),
                    "received_at_utc": iso(datetime.now(UTC)),
                    "key_slot": slot,
                    "quota": {k: resp.headers.get(f"x-requests-{k}") for k in ("remaining", "used", "last")},
                    "failed_key_slots": failures,
                }
        except urllib.error.HTTPError as exc:
            failures.append({"slot": slot, "http_status": exc.code})
        except Exception as exc:
            failures.append({"slot": slot, "error": type(exc).__name__})
    raise CaptureError(f"CFB_FORWARD_ALL_ODDS_KEYS_FAILED:{failures}")


def fetch_event_index(keys: list[str], opener: Callable[..., Any]) -> dict[str, Any]:
    if not keys:
        raise CaptureError("CFB_FORWARD_NO_ODDS_API_KEY")
    result = get_json(
        lambda key: f"{API_ROOT}/sports/{SPORT_KEY}/events?" + urllib.parse.urlencode({"apiKey": key}),
        keys,
        opener,
    )
    if not isinstance(result["payload"], list):
        raise CaptureError("CFB_FORWARD_EVENT_INDEX_MALFORMED")
    return result


def fetch_bulk_main(keys: list[str], opener: Callable[..., Any]) -> dict[str, Any]:
    def build(key: str) -> str:
        q = urllib.parse.urlencode({
            "apiKey": key, "regions": "us", "markets": ",".join(MAIN_MARKETS),
            "oddsFormat": "american", "bookmakers": BOOK,
        })
        return f"{API_ROOT}/sports/{SPORT_KEY}/odds?{q}"
    result = get_json(build, keys, opener)
    if not isinstance(result["payload"], list):
        raise CaptureError("CFB_FORWARD_BULK_ODDS_MALFORMED")
    return result


def fetch_event_close(event_id: str, keys: list[str], opener: Callable[..., Any]) -> dict[str, Any]:
    def build(key: str) -> str:
        q = urllib.parse.urlencode({
            "apiKey": key, "regions": "us", "markets": ",".join(CLOSE_MARKETS),
            "oddsFormat": "american", "bookmakers": BOOK,
        })
        return f"{API_ROOT}/sports/{SPORT_KEY}/events/{event_id}/odds?{q}"
    result = get_json(build, keys, opener)
    if not isinstance(result["payload"], Mapping):
        raise CaptureError("CFB_FORWARD_EVENT_ODDS_MALFORMED")
    return result


def first_admissible(policy: Mapping[str, Any]) -> date:
    return date.fromisoformat(str(policy["first_admissible_slate_ct"]))


def event_start(event: Mapping[str, Any]) -> datetime | None:
    try:
        return parse_ts(event.get("commence_time"))
    except CaptureError:
        return None


def opener_window(now: datetime, policy: Mapping[str, Any]) -> tuple[datetime, datetime] | None:
    local = now.astimezone(CT)
    if local.weekday() != 0 or local.hour != 9:
        return None
    saturday = local.date() + timedelta(days=5)
    if saturday < first_admissible(policy):
        return None
    start = datetime.combine(saturday, dtime.min, tzinfo=CT)
    return start.astimezone(UTC), (start + timedelta(days=3)).astimezone(UTC)


def market_rows(event: Mapping[str, Any], captured_at: datetime) -> list[dict[str, Any]]:
    book = next((b for b in event.get("bookmakers") or [] if str(b.get("key") or "").lower() == BOOK), None)
    if not book:
        return []
    rows = []
    for market in book.get("markets") or []:
        outcomes = list(market.get("outcomes") or [])
        if not outcomes:
            continue
        updated = market.get("last_update") or book.get("last_update")
        age = None
        if updated:
            try:
                age = max(0.0, (captured_at - parse_ts(updated)).total_seconds())
            except CaptureError:
                pass
        for outcome in outcomes:
            rows.append({
                "market": market.get("key"),
                "outcome": outcome.get("name"),
                "point": outcome.get("point"),
                "price_american": outcome.get("price"),
                "market_last_update": updated,
                "quote_age_seconds": age,
                "two_sided_skew_seconds": 0 if len(outcomes) >= 2 and updated else None,
                "book_limit_status": "UNKNOWN_PROVIDER_NOT_EXPOSED",
                "promotion_grade_quote_eligible": False,
                "promotion_grade_blocker": "BOOK_LIMIT_STATUS_UNKNOWN",
            })
    return rows


def base_record(policy_path: Path, policy: Mapping[str, Any], captured_at: datetime) -> dict[str, Any]:
    return {
        "schema_version": "CFB_FORWARD_MARKET_CAPTURE_V1",
        "policy_id": policy["policy_id"],
        "policy_version": policy["version"],
        "policy_sha256": sha256_file(policy_path),
        "captured_at_utc": iso(captured_at),
        "sport": "CFB",
        "sport_key": SPORT_KEY,
        "book": "DraftKings",
        "evidence_class": "RAW_MARKET_CAPTURE_NOT_EVIDENCE_BY_ITSELF",
        "model_p": None,
        "promotion_authority": False,
        "evidence_clock_authority": False,
        "backfill": False,
        "provider_limit_status_available": False,
    }


def write_once(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise CaptureError(f"CFB_FORWARD_REFUSING_OVERWRITE:{path}")
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def capture_opener(*, now: datetime, policy_path: Path, policy: Mapping[str, Any], out_dir: Path,
                   keys: list[str], opener: Callable[..., Any], dry_run: bool) -> dict[str, Any]:
    window = opener_window(now, policy)
    report = {"phase": "OPENER", "due": bool(window), "dry_run": dry_run}
    if not window:
        return report
    start, end = window
    slate = start.astimezone(CT).date().isoformat()
    path = out_dir / "cfb_forward_clv" / "captures" / slate / "opener.json"
    if path.exists():
        return {**report, "status": "ALREADY_CAPTURED", "path": str(path), "slate_start_ct": slate}
    idx = fetch_event_index(keys, opener)
    wanted_events = [e for e in idx["payload"] if (ts := event_start(e)) is not None and start <= ts < end]
    report.update(events_in_scope=len(wanted_events), slate_start_ct=slate)
    if dry_run or not wanted_events:
        return report
    odds = fetch_bulk_main(keys, opener)
    wanted = {str(e.get("id")) for e in wanted_events}
    captured_at = parse_ts(odds["received_at_utc"])
    games = []
    for event in odds["payload"]:
        if str(event.get("id")) not in wanted:
            continue
        games.append({
            "event_id": event.get("id"), "commence_time": event.get("commence_time"),
            "home_team": event.get("home_team"), "away_team": event.get("away_team"),
            "markets": market_rows(event, captured_at),
        })
    record = {
        **base_record(policy_path, policy, captured_at),
        "capture_kind": "OPENER", "target_ct": f"{now.astimezone(CT).date()}T09:00:00",
        "slate_start_ct": slate,
        "api": {k: odds[k] for k in ("raw_sha256", "received_at_utc", "key_slot", "quota", "failed_key_slots")},
        "games": games,
    }
    write_once(path, record)
    return {**report, "rows": sum(len(g["markets"]) for g in games), "path": str(path)}


def close_candidates(events: Iterable[Mapping[str, Any]], now: datetime, policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    for raw in events:
        event = dict(raw)
        start = event_start(event)
        if start is None or start.astimezone(CT).date() < first_admissible(policy):
            continue
        lead = (start - now).total_seconds()
        if 60 <= lead <= 900:
            out.append(event)
    return sorted(out, key=lambda e: (event_start(e) or datetime.max.replace(tzinfo=UTC), str(e.get("id"))))


def close_path(out_dir: Path, event: Mapping[str, Any]) -> Path:
    start = event_start(event)
    if start is None:
        raise CaptureError("CFB_FORWARD_EVENT_START_MISSING")
    slate = start.astimezone(CT).date().isoformat()
    return out_dir / "cfb_forward_clv" / "captures" / slate / "close" / f"{event['id']}.json"


def capture_close_event(*, event: Mapping[str, Any], now_fn: Callable[[], datetime], sleep_fn: Callable[[float], None],
                        policy_path: Path, policy: Mapping[str, Any], out_dir: Path, keys: list[str],
                        opener: Callable[..., Any]) -> dict[str, Any]:
    start = event_start(event)
    if start is None:
        raise CaptureError("CFB_FORWARD_EVENT_START_MISSING")
    target = start - timedelta(seconds=60)
    if now_fn() >= start:
        raise CaptureError("CFB_FORWARD_POST_START_CAPTURE_PROHIBITED")
    path = close_path(out_dir, event)
    if path.exists():
        return {"event_id": event.get("id"), "status": "ALREADY_CAPTURED", "path": str(path)}

    fallback = None
    failures = []
    current = now_fn()
    while current < target and fallback is None:
        try:
            fallback = fetch_event_close(str(event["id"]), keys, opener)
        except CaptureError as exc:
            failures.append(str(exc))
            sleep_fn(min(60.0, max(0.0, (target - current).total_seconds())))
        current = now_fn()
    if current < target:
        sleep_fn((target - current).total_seconds())
        current = now_fn()

    target_result = None
    if current < start:
        try:
            target_result = fetch_event_close(str(event["id"]), keys, opener)
        except CaptureError as exc:
            failures.append(str(exc))
    chosen = target_result or fallback
    if chosen is None:
        return {"event_id": event.get("id"), "status": "CLV_MISSING",
                "reason": "NO_SUCCESSFUL_CLOSE_QUOTE_IN_FROZEN_WINDOW", "failures": failures}
    received = parse_ts(chosen["received_at_utc"])
    if received >= start:
        raise CaptureError("CFB_FORWARD_POST_START_PROVIDER_RESPONSE")
    payload = dict(chosen["payload"])
    status = "TARGET_T_MINUS_60" if target_result is not None else "FALLBACK_WITHIN_RETRY_WINDOW"
    record = {
        **base_record(policy_path, policy, received),
        "capture_kind": "CLOSE", "capture_status": status,
        "event_id": event.get("id"), "commence_time": event.get("commence_time"),
        "home_team": event.get("home_team"), "away_team": event.get("away_team"),
        "target_utc": iso(target), "seconds_before_kickoff": round((start - received).total_seconds(), 3),
        "exact_contract_alt_ladders_requested": True, "requested_markets": list(CLOSE_MARKETS),
        "api": {k: chosen[k] for k in ("raw_sha256", "received_at_utc", "key_slot", "quota", "failed_key_slots")},
        "markets": market_rows(payload, received), "retry_failures": failures,
    }
    write_once(path, record)
    return {"event_id": event.get("id"), "status": status, "path": str(path), "market_rows": len(record["markets"])}


def capture_close(*, now: datetime, policy_path: Path, policy: Mapping[str, Any], out_dir: Path,
                  keys: list[str], opener: Callable[..., Any], dry_run: bool,
                  now_fn: Callable[[], datetime] | None = None,
                  sleep_fn: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    idx = fetch_event_index(keys, opener)
    due = close_candidates(idx["payload"], now, policy)
    report = {"phase": "CLOSE", "events_due": len(due), "dry_run": dry_run, "events": []}
    if dry_run or not due:
        return report
    now_fn = now_fn or (lambda: datetime.now(UTC))
    for event in due:
        report["events"].append(capture_close_event(
            event=event, now_fn=now_fn, sleep_fn=sleep_fn, policy_path=policy_path,
            policy=policy, out_dir=out_dir, keys=keys, opener=opener,
        ))
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("phase", choices=("check", "opener", "close"))
    ap.add_argument("--policy", default=DEFAULT_POLICY)
    ap.add_argument("--out-dir", default=".")
    ap.add_argument("--status-out")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now")
    args = ap.parse_args(argv)
    try:
        policy_path = Path(args.policy)
        policy = load_policy(policy_path)
        now = parse_ts(args.now) if args.now else datetime.now(UTC)
        keys = api_keys()
        if not keys:
            raise CaptureError("CFB_FORWARD_NO_ODDS_API_KEY")
        if args.phase == "check":
            report = {"status": "READY", "phase": "CHECK", "policy_id": policy["policy_id"],
                      "policy_version": policy["version"], "policy_sha256": sha256_file(policy_path),
                      "first_admissible_slate_ct": policy["first_admissible_slate_ct"],
                      "book_limit_status_transport": "UNAVAILABLE_FAIL_CLOSED"}
        elif args.phase == "opener":
            report = capture_opener(now=now, policy_path=policy_path, policy=policy, out_dir=Path(args.out_dir),
                                    keys=keys, opener=default_opener, dry_run=args.dry_run)
        else:
            report = capture_close(now=now, policy_path=policy_path, policy=policy, out_dir=Path(args.out_dir),
                                   keys=keys, opener=default_opener, dry_run=args.dry_run)
        report.setdefault("status", "SUCCESS")
        rc = 0
    except CaptureError as exc:
        report, rc = {"status": "BLOCKED", "reason": str(exc)}, 2
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.status_out:
        p = Path(args.status_out); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text + "\n")
    print(text)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
