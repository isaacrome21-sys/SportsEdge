#!/usr/bin/env python3
"""Prospective raw capture for CFB_FORWARD_CLV_POLICY_V1.

Raw market snapshots are not evidence by themselves. The lane is fail-closed:
no Model_P creation, no Layer-B admission, no backfill, no post-start evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
ODDS_ROOT = "https://api.the-odds-api.com/v4"
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary"
SPORT_KEY = "americanfootball_ncaaf"
BOOK = "draftkings"
MAIN_MARKETS = ("h2h", "spreads", "totals")
CLOSE_MARKETS = ("h2h", "spreads", "totals", "alternate_spreads", "alternate_totals")
DEFAULT_POLICY = "config/cfb_forward_clv_policy_v1.json"
KEY_VARS = tuple(f"SPORTSEDGE_ODDS_API_KEY{suffix}" for suffix in ("", "_2", "_3", "_4"))


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


def norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def load_policy(path: Path) -> dict[str, Any]:
    p = json.loads(path.read_text(encoding="utf-8"))
    if p.get("policy_id") != "CFB_FORWARD_CLV_POLICY_V1" or p.get("status") != "FROZEN":
        raise CaptureError("CFB_FORWARD_POLICY_NOT_FROZEN")
    adm, clv, close = p.get("row_admissibility") or {}, p.get("clv_definition") or {}, (p.get("capture_schedule") or {}).get("close") or {}
    required = [
        (adm.get("model_p_required") is True, "MODEL_P_REQUIREMENT"),
        (adm.get("layer_b_rows_prohibited") is True, "LAYER_B_PROHIBITION"),
        (adm.get("backfill_prohibited") is True, "BACKFILL_PROHIBITION"),
        (clv.get("basis") == "EXACT_ORIGINAL_CONTRACT", "EXACT_CONTRACT"),
        (clv.get("alternate_line_capture_required") is True, "ALT_LINE_CAPTURE"),
        (clv.get("normal_approx_v1", {}).get("permitted_for_promotion_evidence") is False, "NORMAL_APPROX_BLOCK"),
        ((p.get("quote_hygiene") or {}).get("book_limit_status_required") is True, "LIMIT_STATUS_REQUIREMENT"),
        (close.get("selection_rule") == "LAST_SUCCESSFUL_VALID_CAPTURE", "CLOSE_SELECTION_RULE"),
        (close.get("post_start_capture_prohibited") is True, "POST_START_PROHIBITION"),
        (close.get("actual_start_attestation") is not None, "ACTUAL_START_ATTESTATION"),
    ]
    failed = [name for ok, name in required if not ok]
    if failed:
        raise CaptureError("CFB_FORWARD_POLICY_GUARD_FAILED:" + ",".join(failed))
    return p


def api_keys() -> list[str]:
    return [v for name in KEY_VARS if (v := str(os.environ.get(name) or "").strip())]


def default_opener(req: urllib.request.Request, timeout: int = 30):
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_json_url(url: str, opener: Callable[..., Any], *, user_agent: str = "sportsedge-cfb-forward-clv") -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with opener(req, timeout=30) as resp:
        raw = resp.read()
    return {"payload": json.loads(raw), "raw_sha256": sha256_bytes(raw), "received_at_utc": iso(datetime.now(UTC))}


def odds_json(build_url: Callable[[str], str], keys: Iterable[str], opener: Callable[..., Any]) -> dict[str, Any]:
    failures = []
    for slot, key in enumerate(keys, 1):
        try:
            result = fetch_json_url(build_url(key), opener)
            result.update(key_slot=slot, failed_key_slots=failures)
            return result
        except urllib.error.HTTPError as exc:
            failures.append({"slot": slot, "http_status": exc.code})
        except Exception as exc:
            failures.append({"slot": slot, "error": type(exc).__name__})
    raise CaptureError(f"CFB_FORWARD_ALL_ODDS_KEYS_FAILED:{failures}")


def fetch_event_index(keys: list[str], opener: Callable[..., Any]) -> dict[str, Any]:
    if not keys:
        raise CaptureError("CFB_FORWARD_NO_ODDS_API_KEY")
    result = odds_json(lambda key: f"{ODDS_ROOT}/sports/{SPORT_KEY}/events?" + urllib.parse.urlencode({"apiKey": key}), keys, opener)
    if not isinstance(result["payload"], list):
        raise CaptureError("CFB_FORWARD_EVENT_INDEX_MALFORMED")
    return result


def fetch_bulk_main(keys: list[str], opener: Callable[..., Any]) -> dict[str, Any]:
    def build(key: str) -> str:
        q = urllib.parse.urlencode({"apiKey": key, "regions": "us", "markets": ",".join(MAIN_MARKETS), "oddsFormat": "american", "bookmakers": BOOK})
        return f"{ODDS_ROOT}/sports/{SPORT_KEY}/odds?{q}"
    result = odds_json(build, keys, opener)
    if not isinstance(result["payload"], list):
        raise CaptureError("CFB_FORWARD_BULK_ODDS_MALFORMED")
    return result


def fetch_event_close(event_id: str, keys: list[str], opener: Callable[..., Any]) -> dict[str, Any]:
    def build(key: str) -> str:
        q = urllib.parse.urlencode({"apiKey": key, "regions": "us", "markets": ",".join(CLOSE_MARKETS), "oddsFormat": "american", "bookmakers": BOOK})
        return f"{ODDS_ROOT}/sports/{SPORT_KEY}/events/{event_id}/odds?{q}"
    result = odds_json(build, keys, opener)
    if not isinstance(result["payload"], Mapping):
        raise CaptureError("CFB_FORWARD_EVENT_ODDS_MALFORMED")
    return result


def fetch_espn_scoreboard(day: date, opener: Callable[..., Any]) -> dict[str, Any]:
    q = urllib.parse.urlencode({"dates": day.strftime("%Y%m%d"), "groups": "80", "limit": "1000"})
    result = fetch_json_url(f"{ESPN_SCOREBOARD}?{q}", opener)
    if not isinstance(result["payload"], Mapping):
        raise CaptureError("CFB_FORWARD_ESPN_SCOREBOARD_MALFORMED")
    return result


def fetch_espn_summary(event_id: str, opener: Callable[..., Any]) -> dict[str, Any]:
    result = fetch_json_url(f"{ESPN_SUMMARY}?" + urllib.parse.urlencode({"event": event_id}), opener)
    if not isinstance(result["payload"], Mapping):
        raise CaptureError("CFB_FORWARD_ESPN_SUMMARY_MALFORMED")
    return result


def espn_comp(event: Mapping[str, Any]) -> Mapping[str, Any]:
    comps = event.get("competitions") or []
    return comps[0] if comps and isinstance(comps[0], Mapping) else {}


def espn_aliases(comp: Mapping[str, Any], home_away: str) -> set[str]:
    for c in comp.get("competitors") or []:
        if c.get("homeAway") != home_away:
            continue
        team = c.get("team") or {}
        return {norm(team.get(k)) for k in ("displayName", "shortDisplayName", "name", "location", "abbreviation") if norm(team.get(k))}
    return set()


def espn_events(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    for e in payload.get("events") or []:
        comp = espn_comp(e)
        status = (comp.get("status") or e.get("status") or {}).get("type") or {}
        out.append({
            "espn_event_id": str(e.get("id") or ""),
            "scheduled_start_utc": comp.get("date") or e.get("date"),
            "home_aliases": espn_aliases(comp, "home"),
            "away_aliases": espn_aliases(comp, "away"),
            "status_state": str(status.get("state") or "UNKNOWN").lower(),
            "status_name": str(status.get("name") or "UNKNOWN"),
            "status_detail": str(status.get("detail") or ""),
            "completed": bool(status.get("completed")),
        })
    return [x for x in out if x["espn_event_id"]]


def match_espn(odds_event: Mapping[str, Any], candidates: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    home, away = norm(odds_event.get("home_team")), norm(odds_event.get("away_team"))
    hits = [dict(e) for e in candidates if home in e.get("home_aliases", set()) and away in e.get("away_aliases", set())]
    return hits[0] if len(hits) == 1 else None


def status_is_pre(status: Mapping[str, Any], received_at: datetime, policy: Mapping[str, Any]) -> tuple[bool, str]:
    max_age = int(policy["capture_schedule"]["close"]["max_status_read_age_seconds"])
    age = max(0.0, (datetime.now(UTC) - received_at).total_seconds())
    if age > max_age:
        return False, "STATUS_READ_STALE"
    name = str(status.get("status_name") or "").upper()
    if "POSTPON" in name or "CANCEL" in name:
        return False, "VOID_POSTPONED"
    if status.get("status_state") != "pre" or status.get("completed"):
        return False, "EVENT_NOT_PRE_START"
    return True, "PRE_START_CONFIRMED"


def first_admissible(policy: Mapping[str, Any]) -> date:
    return date.fromisoformat(str(policy["first_admissible_slate_ct"]))


def event_start(event: Mapping[str, Any]) -> datetime | None:
    try:
        return parse_ts(event.get("commence_time"))
    except CaptureError:
        return None


def market_rows(event: Mapping[str, Any], captured_at: datetime, policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    book = next((b for b in event.get("bookmakers") or [] if str(b.get("key") or "").lower() == BOOK), None)
    if not book:
        return []
    rows = []
    max_age = int(policy["quote_hygiene"]["max_quote_age_seconds"])
    for market in book.get("markets") or []:
        outcomes = list(market.get("outcomes") or [])
        updated = market.get("last_update") or book.get("last_update")
        try:
            age = max(0.0, (captured_at - parse_ts(updated)).total_seconds()) if updated else None
        except CaptureError:
            age = None
        open_two_sided = len(outcomes) >= 2 and age is not None and age <= max_age
        blockers = ["BOOK_LIMIT_STATUS_UNKNOWN", "TWO_SIDED_SYNC_UNVERIFIED"]
        if not open_two_sided:
            blockers.append("BOOK_MARKET_NOT_OPEN_TWO_SIDED_FRESH")
        for outcome in outcomes:
            rows.append({
                "market": market.get("key"), "outcome": outcome.get("name"), "point": outcome.get("point"),
                "price_american": outcome.get("price"), "market_last_update": updated, "quote_age_seconds": age,
                "book_market_open_two_sided": open_two_sided,
                "two_sided_skew_seconds": None,
                "two_sided_synchronization_status": "PROVIDER_MARKET_LEVEL_TIMESTAMP_ONLY_UNVERIFIED",
                "book_limit_status": "UNKNOWN_PROVIDER_NOT_EXPOSED",
                "promotion_grade_quote_eligible": False,
                "promotion_grade_blockers": blockers,
            })
    return rows


def required_main_markets_open(rows: Iterable[Mapping[str, Any]]) -> bool:
    rows = list(rows)
    return all(any(r.get("market") == m and r.get("book_market_open_two_sided") is True for r in rows) for m in MAIN_MARKETS)


def base_record(policy_path: Path, policy: Mapping[str, Any], captured_at: datetime) -> dict[str, Any]:
    return {
        "schema_version": "CFB_FORWARD_MARKET_CAPTURE_V1",
        "policy_id": policy["policy_id"], "policy_version": policy["version"], "policy_sha256": sha256_file(policy_path),
        "captured_at_utc": iso(captured_at), "sport": "CFB", "sport_key": SPORT_KEY, "book": "DraftKings",
        "evidence_class": "RAW_MARKET_CAPTURE_NOT_EVIDENCE_BY_ITSELF", "model_p": None,
        "promotion_authority": False, "evidence_clock_authority": False, "backfill": False,
        "provider_limit_status_available": False,
    }


def write_once(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise CaptureError(f"CFB_FORWARD_REFUSING_OVERWRITE:{path}")
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def scoreboard_range(days: Iterable[date], opener: Callable[..., Any]) -> list[dict[str, Any]]:
    out = []
    for day in days:
        out.extend(espn_events(fetch_espn_scoreboard(day, opener)["payload"]))
    return out


def opener_window(now: datetime, policy: Mapping[str, Any]) -> tuple[datetime, datetime] | None:
    local = now.astimezone(CT)
    if local.weekday() != 0 or local.hour != 9:
        return None
    saturday = local.date() + timedelta(days=5)
    if saturday < first_admissible(policy):
        return None
    start = datetime.combine(saturday, dtime.min, tzinfo=CT)
    return start.astimezone(UTC), (start + timedelta(days=3)).astimezone(UTC)


def capture_opener(*, now: datetime, policy_path: Path, policy: Mapping[str, Any], out_dir: Path, keys: list[str], opener: Callable[..., Any], dry_run: bool) -> dict[str, Any]:
    window = opener_window(now, policy)
    report = {"phase": "OPENER", "due": bool(window), "dry_run": dry_run}
    if not window:
        return report
    start, end = window
    slate = start.astimezone(CT).date().isoformat()
    path = out_dir / "cfb_forward_clv" / "captures" / slate / "opener.json"
    if path.exists():
        return {**report, "status": "ALREADY_CAPTURED", "path": str(path)}
    days = [(start.astimezone(CT).date() + timedelta(days=i)) for i in range(3)]
    fbs = scoreboard_range(days, opener)
    idx = fetch_event_index(keys, opener)
    wanted = [e for e in idx["payload"] if (ts := event_start(e)) is not None and start <= ts < end and match_espn(e, fbs)]
    report.update(events_in_scope=len(wanted), slate_start_ct=slate)
    if dry_run or not wanted:
        return report
    odds = fetch_bulk_main(keys, opener)
    ids = {str(e.get("id")) for e in wanted}
    captured = parse_ts(odds["received_at_utc"])
    games = []
    for e in odds["payload"]:
        if str(e.get("id")) in ids:
            games.append({"event_id": e.get("id"), "commence_time": e.get("commence_time"), "home_team": e.get("home_team"), "away_team": e.get("away_team"), "markets": market_rows(e, captured, policy)})
    write_once(path, {**base_record(policy_path, policy, captured), "capture_kind": "OPENER", "slate_start_ct": slate, "fbs_scope_source": "ESPN_GROUP_80", "games": games})
    return {**report, "status": "CAPTURED", "path": str(path), "games": len(games)}


def free_gate_due_espn(now: datetime, policy: Mapping[str, Any], opener: Callable[..., Any]) -> tuple[list[dict[str, Any]], datetime]:
    local = now.astimezone(CT)
    board = fetch_espn_scoreboard(local.date(), opener)
    received = parse_ts(board["received_at_utc"])
    due = []
    for e in espn_events(board["payload"]):
        try:
            scheduled = parse_ts(e["scheduled_start_utc"])
        except CaptureError:
            continue
        if scheduled.astimezone(CT).date() < first_admissible(policy):
            continue
        lead = (scheduled - now).total_seconds()
        pre, reason = status_is_pre(e, received, policy)
        # Scheduled time only seeds monitoring. Keep delayed PRE events alive for six hours.
        if pre and -21600 <= lead <= 1200:
            e["status_validation"] = reason
            due.append(e)
    return due, received


def raw_snapshot_path(out_dir: Path, event: Mapping[str, Any], captured: datetime) -> Path:
    scheduled = event_start(event)
    if scheduled is None:
        raise CaptureError("CFB_FORWARD_EVENT_START_MISSING")
    slate = scheduled.astimezone(CT).date().isoformat()
    stamp = captured.strftime("%Y%m%dT%H%M%S%fZ")
    return out_dir / "cfb_forward_clv" / "captures" / slate / "close_raw" / str(event["id"]) / f"{stamp}.json"


def capture_close_snapshot(*, now: datetime, policy_path: Path, policy: Mapping[str, Any], out_dir: Path, keys: list[str], opener: Callable[..., Any], dry_run: bool) -> dict[str, Any]:
    espn_due, status_received = free_gate_due_espn(now, policy, opener)
    report = {"phase": "CLOSE", "dry_run": dry_run, "espn_due": len(espn_due), "events": []}
    if not espn_due:
        return report
    idx = fetch_event_index(keys, opener)
    odds_due = []
    for e in idx["payload"]:
        matched = match_espn(e, espn_due)
        if matched:
            odds_due.append((e, matched))
    report["matched_odds_events"] = len(odds_due)
    if dry_run:
        return report
    for e, status in odds_due:
        result = fetch_event_close(str(e["id"]), keys, opener)
        captured = parse_ts(result["received_at_utc"])
        fresh_board = fetch_espn_scoreboard(captured.astimezone(CT).date(), opener)
        fresh_received = parse_ts(fresh_board["received_at_utc"])
        fresh_match = match_espn(e, espn_events(fresh_board["payload"]))
        pre, status_reason = status_is_pre(fresh_match or {}, fresh_received, policy)
        if not pre:
            report["events"].append({"event_id": e.get("id"), "status": "INVALID", "reason": status_reason})
            continue
        payload = dict(result["payload"])
        rows = market_rows(payload, captured, policy)
        if not required_main_markets_open(rows):
            report["events"].append({"event_id": e.get("id"), "status": "INVALID", "reason": "DK_PREGAME_MAIN_MARKETS_NOT_OPEN_TWO_SIDED_FRESH"})
            continue
        path = raw_snapshot_path(out_dir, e, captured)
        record = {
            **base_record(policy_path, policy, captured),
            "capture_kind": "CLOSE_RAW_SNAPSHOT", "capture_status": "PENDING_FIRST_PLAY_ATTESTATION",
            "odds_event_id": e.get("id"), "espn_event_id": fresh_match.get("espn_event_id"),
            "scheduled_commence_time": e.get("commence_time"), "home_team": e.get("home_team"), "away_team": e.get("away_team"),
            "espn_status": {k: fresh_match.get(k) for k in ("status_state", "status_name", "status_detail", "completed")},
            "espn_status_received_at_utc": iso(fresh_received),
            "dk_pregame_main_markets_open_two_sided_fresh": True,
            "exact_contract_alt_ladders_requested": True, "requested_markets": list(CLOSE_MARKETS),
            "first_play_attestation_status": "PENDING_POST_START",
            "markets": rows,
        }
        write_once(path, record)
        report["events"].append({"event_id": e.get("id"), "status": "CAPTURED_PENDING_ATTESTATION", "path": str(path), "market_rows": len(rows)})
    return report


def iter_wallclocks(obj: Any) -> Iterable[datetime]:
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            if str(k).lower() == "wallclock" and isinstance(v, str):
                try:
                    yield parse_ts(v)
                except CaptureError:
                    pass
            elif k in {"plays", "drives"}:
                yield from iter_wallclocks(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_wallclocks(item)


def first_play_from_summary(payload: Mapping[str, Any]) -> datetime | None:
    vals = sorted(iter_wallclocks(payload))
    return vals[0] if vals else None


def selected_path_for(snapshot: Path) -> Path:
    # .../<slate>/close_raw/<odds_id>/<timestamp>.json -> .../<slate>/close_selected/<odds_id>.json
    slate_dir = snapshot.parents[2]
    return slate_dir / "close_selected" / f"{snapshot.parent.name}.json"


def attest_existing(*, out_dir: Path, policy_path: Path, policy: Mapping[str, Any], opener: Callable[..., Any], dry_run: bool) -> dict[str, Any]:
    root = out_dir / "cfb_forward_clv" / "captures"
    groups: dict[Path, list[Path]] = {}
    if root.exists():
        for snap in root.glob("*/close_raw/*/*.json"):
            groups.setdefault(selected_path_for(snap), []).append(snap)
    report = {"phase": "ATTEST", "dry_run": dry_run, "groups": len(groups), "events": []}
    for selected, snaps in sorted(groups.items(), key=lambda kv: str(kv[0])):
        if selected.exists():
            continue
        records = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(snaps)]
        espn_id = str(records[0].get("espn_event_id") or "")
        if not espn_id:
            report["events"].append({"status": "PENDING", "reason": "ESPN_EVENT_ID_MISSING"})
            continue
        summary = fetch_espn_summary(espn_id, opener)
        first_play = first_play_from_summary(summary["payload"])
        if first_play is None:
            report["events"].append({"espn_event_id": espn_id, "status": "PENDING", "reason": "FIRST_PLAY_TIMESTAMP_UNAVAILABLE"})
            continue
        valid = []
        invalid = []
        for p, r in zip(sorted(snaps), records):
            captured = parse_ts(r["captured_at_utc"])
            (valid if captured < first_play else invalid).append((captured, p, r))
        chosen = max(valid, key=lambda x: x[0]) if valid else None
        outcome = {
            **base_record(policy_path, policy, datetime.now(UTC)),
            "capture_kind": "CLOSE_SELECTION_ATTESTATION",
            "espn_event_id": espn_id,
            "actual_start_attestation": "FIRST_PLAY_WALLCLOCK",
            "first_play_utc": iso(first_play),
            "selection_rule": "LAST_SUCCESSFUL_VALID_CAPTURE",
            "invalid_post_start_snapshot_count": len(invalid),
            "raw_snapshot_count": len(records),
        }
        if chosen:
            outcome.update(status="SELECTED", selected_snapshot=str(chosen[1].relative_to(out_dir)), selected_snapshot_sha256=sha256_file(chosen[1]), selected_capture_utc=iso(chosen[0]), seconds_before_first_play=round((first_play - chosen[0]).total_seconds(), 3))
        else:
            outcome.update(status="CLV_MISSING", reason="NO_VALID_PRE_FIRST_PLAY_CAPTURE")
        if dry_run:
            report["events"].append({"espn_event_id": espn_id, "status": outcome["status"]})
        else:
            write_once(selected, outcome)
            report["events"].append({"espn_event_id": espn_id, "status": outcome["status"], "path": str(selected)})
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("phase", choices=("check", "opener", "close", "attest"))
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
        if args.phase in {"opener", "close"} and not keys:
            raise CaptureError("CFB_FORWARD_NO_ODDS_API_KEY")
        if args.phase == "check":
            report = {"status": "READY", "phase": "CHECK", "policy_id": policy["policy_id"], "policy_version": policy["version"], "policy_sha256": sha256_file(policy_path), "first_admissible_slate_ct": policy["first_admissible_slate_ct"], "book_limit_status_transport": "UNAVAILABLE_FAIL_CLOSED", "two_sided_sync_transport": "MARKET_LEVEL_ONLY_FAIL_CLOSED"}
        elif args.phase == "opener":
            report = capture_opener(now=now, policy_path=policy_path, policy=policy, out_dir=Path(args.out_dir), keys=keys, opener=default_opener, dry_run=args.dry_run)
        elif args.phase == "close":
            report = capture_close_snapshot(now=now, policy_path=policy_path, policy=policy, out_dir=Path(args.out_dir), keys=keys, opener=default_opener, dry_run=args.dry_run)
        else:
            report = attest_existing(out_dir=Path(args.out_dir), policy_path=policy_path, policy=policy, opener=default_opener, dry_run=args.dry_run)
        report.setdefault("status", "SUCCESS")
        rc = 0
    except CaptureError as exc:
        report, rc = {"status": "BLOCKED", "reason": str(exc)}, 2
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.status_out:
        p = Path(args.status_out); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text + "\n", encoding="utf-8")
    print(text)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
