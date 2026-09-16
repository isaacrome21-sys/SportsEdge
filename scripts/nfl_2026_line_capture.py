#!/usr/bin/env python3
"""NFL 2026 confirmation line capture (DraftKings spreads + totals).

DRAFTKINGS_DIRECT_WEB_V1 is primary; DRAFTKINGS_ODDS_API_V1 is fallback only
when the direct source itself fails. A valid direct board with missing/one-sided
markets never triggers cross-source filling.

Before the first lock can be created, every admitted capture must match the
nflverse schedule by exact kickoff-UTC multiplicity and satisfy exact two-sided
spread/total admission. Source modules are content-bound through the locked
configuration.
"""
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.nfl_direct_capture_source import (  # noqa: E402
    DirectCaptureError,
    SOURCE_CLASS as DIRECT_SOURCE_CLASS,
    acquire_board,
    game_rows_direct,
)
from sportsedge.nfl_confirmation_schedule import (  # noqa: E402
    ScheduleExpectationError,
    captured_final_event_ids,
    final_expected_due_kickoffs,
    load_snapshot,
    opener_expected_kickoffs,
    require_exact_coverage,
)

API = "https://api.the-odds-api.com/v4/sports"
API_SOURCE_CLASS = "DRAFTKINGS_ODDS_API_V1"
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
ALLOWED_OPENER_DAYS = {"Sunday", "Monday", "Tuesday"}
CONFIG_PATH = os.environ.get("CAPTURE_CONFIG", "config/nfl_2026_capture.json")


class CaptureError(Exception):
    pass


class DirectSourceFailure(CaptureError):
    def __init__(self, message, attempts=None):
        super().__init__(message)
        self.attempts = list(attempts or [])


def utc_now():
    return datetime.now(timezone.utc)


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_blob_sha(path):
    raw = Path(path).read_bytes()
    digest = hashlib.sha1()
    digest.update(f"blob {len(raw)}\0".encode("ascii"))
    digest.update(raw)
    return digest.hexdigest()


def iso_z(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _atomic_create_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise CaptureError(f"REFUSING_OVERWRITE {path}")
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        with tmp.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError as exc:
            raise CaptureError(f"REFUSING_OVERWRITE {path}") from exc
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _atomic_create_json(path, value):
    payload = (json.dumps(value, indent=2) + "\n").encode("utf-8")
    _atomic_create_bytes(path, payload)


# ---------- config and locking ----------

def load_config():
    cfg = json.loads(Path(CONFIG_PATH).read_text())
    problems = [f"{k} not filled in" for k, v in cfg.items()
                if isinstance(v, str) and v.startswith("REPLACE_")]
    if cfg.get("opener_weekday") not in ALLOWED_OPENER_DAYS:
        problems.append("opener_weekday must be Sunday, Monday or Tuesday")
    try:
        if date.fromisoformat(cfg["week1_tuesday_local_date"]).weekday() != 1:
            problems.append("week1_tuesday_local_date is not a Tuesday")
    except (KeyError, ValueError):
        problems.append("week1_tuesday_local_date invalid")
    if not problems and not Path(cfg["policy_path"]).is_file():
        problems.append(f"policy file not found: {cfg['policy_path']}")
    if cfg.get("source_priority") != [DIRECT_SOURCE_CLASS, API_SOURCE_CLASS]:
        problems.append("source_priority must be direct DraftKings then Odds API")
    if cfg.get("fallback_scope") != "WHOLE_SOURCE_FAILURE_ONLY":
        problems.append("fallback_scope must be WHOLE_SOURCE_FAILURE_ONLY")
    if cfg.get("cross_source_market_merge") is not False:
        problems.append("cross_source_market_merge must be false")
    if cfg.get("direct_valid_board_market_gaps_trigger_fallback") is not False:
        problems.append("direct_valid_board_market_gaps_trigger_fallback must be false")
    if cfg.get("schedule_coverage_semantics") != "EXACT_KICKOFF_UTC_MULTIPLICITY":
        problems.append("schedule_coverage_semantics must be EXACT_KICKOFF_UTC_MULTIPLICITY")
    bindings = cfg.get("source_code_bindings")
    if not isinstance(bindings, dict) or not bindings:
        problems.append("source_code_bindings missing")
    else:
        for path, expected in sorted(bindings.items()):
            try:
                actual = git_blob_sha(path)
            except OSError:
                problems.append(f"source binding path missing: {path}")
                continue
            if actual != expected:
                problems.append(f"source binding mismatch: {path}")
    if problems:
        raise CaptureError("CONFIG_INVALID: " + "; ".join(problems))
    return cfg


def current_hashes(cfg):
    h = {
        "policy_path": cfg["policy_path"],
        "policy_sha256": sha256_file(cfg["policy_path"]),
        "config_sha256": sha256_file(CONFIG_PATH),
        "script_sha256": sha256_file(__file__),
    }
    wf = os.environ.get("WORKFLOW_PATH")
    if wf and Path(wf).is_file():
        h["workflow_sha256"] = sha256_file(wf)
    return h


def lock_status(cfg, hashes, now, create):
    lock = Path(cfg["output_dir"]) / "capture_lock.json"
    if not lock.exists():
        if not create:
            return "NO_LOCK_YET"
        try:
            _atomic_create_json(lock, {**hashes, "locked_at_utc": now.isoformat()})
            return "LOCK_CREATED"
        except CaptureError:
            if not lock.exists():
                raise
    try:
        saved = json.loads(lock.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CaptureError("CAPTURE_LOCK_INVALID") from exc
    diffs = [k for k in hashes if saved.get(k) != hashes[k]]
    return "MATCH" if not diffs else "MISMATCH:" + ",".join(diffs)


def _any_capture_record(cfg):
    root = Path(cfg["output_dir"])
    if any(root.glob("week*/opener.json")):
        return True
    return any(root.glob("week*/final/*.json"))


def rollback_new_lock_if_uncommitted(cfg, hashes, status):
    if status != "LOCK_CREATED" or _any_capture_record(cfg):
        return
    lock = Path(cfg["output_dir"]) / "capture_lock.json"
    try:
        saved = json.loads(lock.read_text())
    except (OSError, json.JSONDecodeError):
        return
    if all(saved.get(k) == v for k, v in hashes.items()):
        lock.unlink(missing_ok=True)


# ---------- Odds API fallback ----------

def api_keys():
    keys = [os.environ.get(f"ODDS_API_KEY_{i}", "").strip() for i in range(1, 5)]
    return [(i + 1, k) for i, k in enumerate(keys) if k]


def api_get(path, params, keys=None):
    keys = keys if keys is not None else api_keys()
    if not keys:
        raise CaptureError("NO_API_KEYS")
    errors = []
    for slot, key in keys:
        url = f"{API}/{path}?" + urllib.parse.urlencode({**params, "apiKey": key})
        req = urllib.request.Request(url, headers={"User-Agent": "sportsedge-line-capture"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
                return {
                    "data": json.loads(body),
                    "raw_sha256": hashlib.sha256(body).hexdigest(),
                    "received_at_utc": utc_now().isoformat(),
                    "key_slot": slot,
                    "quota": {h: resp.headers.get(f"x-requests-{h}") for h in ("remaining", "used", "last")},
                    "failed_key_slots": errors,
                }
        except urllib.error.HTTPError as e:
            errors.append({"key_slot": slot, "http_status": e.code})
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            errors.append({"key_slot": slot, "error": type(e).__name__})
    raise CaptureError(f"ALL_KEYS_FAILED {errors}")


# ---------- weeks and windows ----------

def week_of(dt_utc, cfg):
    local = dt_utc.astimezone(ZoneInfo(cfg["timezone"])).date()
    return (local - date.fromisoformat(cfg["week1_tuesday_local_date"])).days // 7 + 1


def week_bounds_utc(week, cfg):
    tz = ZoneInfo(cfg["timezone"])
    start = date.fromisoformat(cfg["week1_tuesday_local_date"]) + timedelta(days=7 * (week - 1))
    end = start + timedelta(days=7)
    to_utc = lambda d: datetime(d.year, d.month, d.day, tzinfo=tz).astimezone(timezone.utc)
    return to_utc(start), to_utc(end)


def opener_target(local_day, cfg):
    tz = ZoneInfo(cfg["timezone"])
    hh, mm = map(int, cfg["opener_local_time"].split(":"))
    return datetime(local_day.year, local_day.month, local_day.day, hh, mm, tzinfo=tz)


def opener_week_for_day(local_day, cfg):
    tuesday = local_day + timedelta(days=(1 - local_day.weekday()) % 7)
    return (tuesday - date.fromisoformat(cfg["week1_tuesday_local_date"])).days // 7 + 1


def opener_due(now, cfg):
    local = now.astimezone(ZoneInfo(cfg["timezone"]))
    if WEEKDAYS[local.weekday()] != cfg["opener_weekday"]:
        return None
    target = opener_target(local.date(), cfg)
    if not (target <= local < target + timedelta(minutes=cfg["opener_window_minutes"])):
        return None
    week = opener_week_for_day(local.date(), cfg)
    return None if week < cfg["first_week"] else {"week": week, "target": target}


# ---------- normalization/admission ----------

def spread_row(market, home, away):
    if not market:
        return {"status": "MISSING"}
    by = {o.get("name"): o for o in market.get("outcomes", [])}
    h, a = by.get(home), by.get(away)
    if not (h and a):
        return {"status": "ONE_SIDED", "outcomes": market.get("outcomes", [])}
    ok = h.get("point") is not None and a.get("point") is not None and abs(h["point"] + a["point"]) < 1e-9
    return {"status": "OK" if ok else "LINE_MISMATCH", "market_last_update": market.get("last_update"),
            "home_point": h.get("point"), "home_price": h.get("price"),
            "away_point": a.get("point"), "away_price": a.get("price")}


def total_row(market):
    if not market:
        return {"status": "MISSING"}
    by = {o.get("name"): o for o in market.get("outcomes", [])}
    o, u = by.get("Over"), by.get("Under")
    if not (o and u):
        return {"status": "ONE_SIDED", "outcomes": market.get("outcomes", [])}
    ok = o.get("point") is not None and o.get("point") == u.get("point")
    return {"status": "OK" if ok else "LINE_MISMATCH", "market_last_update": market.get("last_update"),
            "point": o.get("point"), "over_price": o.get("price"), "under_price": u.get("price")}


def game_rows(events, odds, cfg, wanted_ids=None):
    odds_by_id = {e["id"]: e for e in odds}
    rows = []
    for ev in events:
        if wanted_ids is not None and ev["id"] not in wanted_ids:
            continue
        o = odds_by_id.get(ev["id"])
        row = {"event_id": ev["id"], "home_team": ev["home_team"], "away_team": ev["away_team"],
               "commence_time": ev["commence_time"], "week": week_of(parse_iso(ev["commence_time"]), cfg),
               "book": cfg["bookmaker"], "source_class": API_SOURCE_CLASS}
        book = next((b for b in (o or {}).get("bookmakers", []) if b.get("key") == cfg["bookmaker"]), None)
        if not book:
            row.update(book_last_update=None, spread={"status": "NOT_LISTED"}, total={"status": "NOT_LISTED"})
        else:
            markets = {m.get("key"): m for m in book.get("markets", [])}
            row.update(book_last_update=book.get("last_update"),
                       spread=spread_row(markets.get("spreads"), ev["home_team"], ev["away_team"]),
                       total=total_row(markets.get("totals")))
        rows.append(row)
    return rows


def require_two_sided(rows, cfg):
    if not rows:
        raise CaptureError("NO_GAMES_IN_CAPTURE_WINDOW")
    failures = []
    for row in rows:
        for market in cfg["markets"]:
            key = "spread" if market == "spreads" else "total" if market == "totals" else None
            if key and row.get(key, {}).get("status") != "OK":
                failures.append({"event_id": row.get("event_id"), "market": market,
                                 "status": row.get(key, {}).get("status")})
    if failures:
        raise CaptureError("TWO_SIDED_ADMISSION_FAILED " + json.dumps(failures, separators=(",", ":")))


def require_schedule_coverage(rows, expected, kind):
    try:
        require_exact_coverage(rows, expected, kind=kind)
    except ScheduleExpectationError as exc:
        raise CaptureError(str(exc)) from exc


def load_schedule_snapshot():
    try:
        return load_snapshot()
    except ScheduleExpectationError as exc:
        raise CaptureError(str(exc)) from exc


# ---------- capture plumbing ----------

def run_meta():
    return {k.lower(): os.environ.get(k) for k in
            ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA", "GITHUB_EVENT_NAME")}


def log_attempt(cfg, entry):
    path = Path(cfg["output_dir"]) / "attempts.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def write_new(path, record):
    _atomic_create_json(path, record)


def persist_direct_raw(cfg, transport):
    raw = transport.get("raw_bytes")
    if not isinstance(raw, (bytes, bytearray)):
        raise CaptureError("DIRECT_RAW_BYTES_MISSING")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != transport.get("raw_sha256"):
        raise CaptureError("DIRECT_RAW_HASH_MISMATCH")
    path = Path(cfg["output_dir"]) / "raw" / "draftkings-direct" / f"{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise CaptureError("DIRECT_RAW_PATH_COLLISION")
    else:
        _atomic_create_bytes(path, bytes(raw))
    return str(path)


def direct_meta(transport, raw_path):
    return {
        "source_class": DIRECT_SOURCE_CLASS,
        "source_uri": transport["source_uri"],
        "transport_host": transport["transport_host"],
        "observed_at_utc": transport["observed_at_utc"],
        "timestamp_semantics": "SPORTSEDGE_HTTP_RESPONSE_RECEIPT_UPPER_BOUND",
        "provider_quote_timestamp_available": False,
        "raw_sha256": transport["raw_sha256"],
        "raw_relative_path": raw_path,
        "attempts": transport["attempts"],
        "adapter_module_sha256": transport["adapter_module_sha256"],
        "github_sha": os.environ.get("GITHUB_SHA"),
    }


def schedule_meta(snapshot, expected):
    return {
        **snapshot.provenance(),
        "expected_kickoffs": dict(sorted(expected.items())),
        "expected_game_count": sum(expected.values()),
    }


def odds_params(cfg, t_from, t_to):
    return {"bookmakers": cfg["bookmaker"], "markets": ",".join(cfg["markets"]),
            "oddsFormat": "american", "dateFormat": "iso",
            "commenceTimeFrom": iso_z(t_from), "commenceTimeTo": iso_z(t_to)}


def predictions_status(cfg, week):
    d = Path(cfg["predictions_dir"])
    files = sorted(p for p in d.glob(f"week{week:02d}*") if p.is_file()) if d.is_dir() else []
    if not files:
        return {"status": "PREDICTIONS_NOT_FOUND"}
    return {"status": "PREDICTIONS_PRESENT",
            "files": [{"path": str(p), "sha256": sha256_file(p)} for p in files]}


def acquire_direct_rows(cfg, window_start=None, window_end=None):
    try:
        transport = acquire_board(cfg["sport_key"])
        rows = game_rows_direct(
            transport,
            week_of=lambda dt: week_of(dt, cfg),
            window_start=window_start,
            window_end=window_end,
        )
    except DirectCaptureError as exc:
        raise DirectSourceFailure(str(exc), getattr(exc, "attempts", [])) from exc
    return transport, rows


def api_opener_rows(cfg, t_from, t_to):
    events = api_get(f"{cfg['sport_key']}/events",
                     {"commenceTimeFrom": iso_z(t_from), "commenceTimeTo": iso_z(t_to), "dateFormat": "iso"})
    odds = api_get(f"{cfg['sport_key']}/odds", odds_params(cfg, t_from, t_to))
    return events, odds, game_rows(events["data"], odds["data"], cfg)


def _write_record_with_lock(path, record, cfg, hashes, now):
    status = lock_status(cfg, hashes, now, create=True)
    record["lock_status"] = status
    try:
        write_new(path, record)
    except Exception:
        rollback_new_lock_if_uncommitted(cfg, hashes, status)
        raise
    return status


# ---------- OPENER ----------

def do_opener(cfg, now, hashes):
    due = opener_due(now, cfg)
    if not due:
        return None
    path = Path(cfg["output_dir"]) / f"week{due['week']:02d}" / "opener.json"
    if path.exists():
        return None

    snapshot = load_schedule_snapshot()
    try:
        expected = opener_expected_kickoffs(cfg, due["week"], snapshot)
    except ScheduleExpectationError as exc:
        raise CaptureError(str(exc)) from exc

    ws, we = week_bounds_utc(due["week"], cfg)
    t_from = max(ws, now)
    direct_failure = None
    try:
        transport, rows = acquire_direct_rows(cfg, t_from, we)
    except DirectSourceFailure as exc:
        direct_failure = exc
        transport = None
        rows = None

    if transport is not None:
        try:
            require_schedule_coverage(rows, expected, "OPENER")
            require_two_sided(rows, cfg)
        except CaptureError as exc:
            log_attempt(cfg, {"run_started_utc": now.isoformat(), "kind": "OPENER", "week": due["week"],
                              "source_class": DIRECT_SOURCE_CLASS, "outcome": str(exc),
                              "attempts": transport["attempts"], **run_meta()})
            raise
        raw_path = persist_direct_raw(cfg, transport)
        retrieved = parse_iso(transport["observed_at_utc"])
        record = {
            "capture_kind": "OPENER", "week": due["week"], "book": cfg["bookmaker"], "markets": cfg["markets"],
            "source_class": DIRECT_SOURCE_CLASS,
            "target_local": due["target"].isoformat(), "run_started_utc": now.isoformat(),
            "retrieved_at_utc": transport["observed_at_utc"],
            "minutes_after_target": round((retrieved - due["target"]).total_seconds() / 60, 2),
            "hashes": hashes, "run": run_meta(),
            "predictions_at_opener": predictions_status(cfg, due["week"]),
            "schedule": schedule_meta(snapshot, expected),
            "transport": direct_meta(transport, raw_path),
            "games": rows,
        }
        status = _write_record_with_lock(path, record, cfg, hashes, now)
        return record

    try:
        events, odds, rows = api_opener_rows(cfg, t_from, we)
        require_schedule_coverage(rows, expected, "OPENER")
        require_two_sided(rows, cfg)
    except CaptureError as exc:
        log_attempt(cfg, {"run_started_utc": now.isoformat(), "kind": "OPENER", "week": due["week"],
                          "source_class": API_SOURCE_CLASS, "outcome": str(exc),
                          "direct_attempts": getattr(direct_failure, "attempts", []), **run_meta()})
        raise
    retrieved = parse_iso(odds["received_at_utc"])
    record = {
        "capture_kind": "OPENER", "week": due["week"], "book": cfg["bookmaker"], "markets": cfg["markets"],
        "source_class": API_SOURCE_CLASS,
        "target_local": due["target"].isoformat(), "run_started_utc": now.isoformat(),
        "retrieved_at_utc": odds["received_at_utc"],
        "minutes_after_target": round((retrieved - due["target"]).total_seconds() / 60, 2),
        "hashes": hashes, "run": run_meta(),
        "predictions_at_opener": predictions_status(cfg, due["week"]),
        "schedule": schedule_meta(snapshot, expected),
        "transport": {
            "source_class": API_SOURCE_CLASS,
            "timestamp_semantics": "SPORTSEDGE_HTTP_RESPONSE_RECEIPT_UPPER_BOUND",
            "provider_quote_timestamp_available": True,
            "direct_attempts": getattr(direct_failure, "attempts", []),
            "events": {x: events[x] for x in ("key_slot", "quota", "failed_key_slots", "raw_sha256", "received_at_utc")},
            "odds": {x: odds[x] for x in ("key_slot", "quota", "failed_key_slots", "raw_sha256", "received_at_utc")},
        },
        "games": rows, "raw_events": events["data"], "raw_odds": odds["data"],
    }
    _write_record_with_lock(path, record, cfg, hashes, now)
    return record


# ---------- FINAL ----------

def captured_final_ids(cfg):
    return captured_final_event_ids(cfg)


def _due_final_rows(rows, cfg, now):
    lead = timedelta(minutes=cfg["final_minutes_before_kickoff"])
    window = timedelta(minutes=cfg["final_window_minutes"])
    done = captured_final_ids(cfg)
    due = []
    for row in rows:
        kickoff = parse_iso(row["commence_time"])
        if row["event_id"] in done or week_of(kickoff, cfg) < cfg["first_week"]:
            continue
        if kickoff - lead <= now < min(kickoff - lead + window, kickoff):
            due.append(row)
    return due


def do_final(cfg, now, hashes):
    snapshot = load_schedule_snapshot()
    try:
        expected = final_expected_due_kickoffs(cfg, now, snapshot)
    except ScheduleExpectationError as exc:
        raise CaptureError(str(exc)) from exc
    if not expected:
        return None

    direct_failure = None
    try:
        transport, board_rows = acquire_direct_rows(cfg)
    except DirectSourceFailure as exc:
        direct_failure = exc
        transport = None
        board_rows = None

    if transport is not None:
        rows = _due_final_rows(board_rows, cfg, now)
        try:
            require_schedule_coverage(rows, expected, "FINAL")
            require_two_sided(rows, cfg)
        except CaptureError as exc:
            log_attempt(cfg, {"run_started_utc": now.isoformat(), "kind": "FINAL",
                              "event_ids": [r.get("event_id") for r in rows],
                              "source_class": DIRECT_SOURCE_CLASS, "outcome": str(exc),
                              "attempts": transport["attempts"], **run_meta()})
            raise
        raw_path = persist_direct_raw(cfg, transport)
        retrieved = parse_iso(transport["observed_at_utc"])
        source_meta = direct_meta(transport, raw_path)
        raw_odds = None
    else:
        lead = timedelta(minutes=cfg["final_minutes_before_kickoff"])
        due_events = []
        odds = None
        try:
            events = api_get(f"{cfg['sport_key']}/events",
                             {"commenceTimeFrom": iso_z(now),
                              "commenceTimeTo": iso_z(now + lead + timedelta(minutes=1)),
                              "dateFormat": "iso"})
            done = captured_final_ids(cfg)
            window = timedelta(minutes=cfg["final_window_minutes"])
            for ev in events["data"]:
                kickoff = parse_iso(ev["commence_time"])
                if ev["id"] in done or week_of(kickoff, cfg) < cfg["first_week"]:
                    continue
                if kickoff - lead <= now < min(kickoff - lead + window, kickoff):
                    due_events.append(ev)
            kicks = [parse_iso(e["commence_time"]) for e in due_events]
            if not kicks:
                raise CaptureError("API_EVENTS_MISSING_DUE_SCHEDULE_GAMES")
            odds = api_get(f"{cfg['sport_key']}/odds",
                           odds_params(cfg, min(kicks), max(kicks) + timedelta(minutes=1)))
            rows = game_rows(due_events, odds["data"], cfg, wanted_ids={e["id"] for e in due_events})
            require_schedule_coverage(rows, expected, "FINAL")
            require_two_sided(rows, cfg)
        except CaptureError as exc:
            log_attempt(cfg, {"run_started_utc": now.isoformat(), "kind": "FINAL",
                              "event_ids": [e.get("id") for e in due_events],
                              "source_class": API_SOURCE_CLASS, "outcome": str(exc),
                              "direct_attempts": getattr(direct_failure, "attempts", []), **run_meta()})
            raise
        retrieved = parse_iso(odds["received_at_utc"])
        source_meta = {
            "source_class": API_SOURCE_CLASS,
            "timestamp_semantics": "SPORTSEDGE_HTTP_RESPONSE_RECEIPT_UPPER_BOUND",
            "provider_quote_timestamp_available": True,
            "direct_attempts": getattr(direct_failure, "attempts", []),
            "odds": {x: odds[x] for x in ("key_slot", "quota", "failed_key_slots", "raw_sha256", "received_at_utc")},
        }
        raw_odds = odds["data"]

    lead = timedelta(minutes=cfg["final_minutes_before_kickoff"])
    for row in rows:
        kickoff = parse_iso(row["commence_time"])
        row["target_utc"] = (kickoff - lead).isoformat()
        row["minutes_before_kickoff"] = round((kickoff - retrieved).total_seconds() / 60, 2)
        if retrieved >= kickoff:
            raise CaptureError("AFTER_KICKOFF_INVALID")

    written = []
    status = None
    for week in sorted({r["week"] for r in rows}):
        stamp = retrieved.strftime("%Y%m%dT%H%M%SZ")
        path = Path(cfg["output_dir"]) / f"week{week:02d}" / "final" / f"{stamp}.json"
        record = {
            "capture_kind": "FINAL", "week": week, "book": cfg["bookmaker"], "markets": cfg["markets"],
            "source_class": source_meta["source_class"],
            "run_started_utc": now.isoformat(), "retrieved_at_utc": iso_z(retrieved),
            "hashes": hashes, "run": run_meta(),
            "schedule": schedule_meta(snapshot, expected),
            "transport": source_meta,
            "games": [r for r in rows if r["week"] == week],
        }
        if raw_odds is not None:
            record["raw_odds"] = raw_odds
        status = _write_record_with_lock(path, record, cfg, hashes, now)
        written.append(record)
    return {"capture_kind": "FINAL", "source_class": source_meta["source_class"],
            "lock_status": status, "records": written}


# ---------- check mode ----------

def do_check(cfg, now, hashes):
    tz = ZoneInfo(cfg["timezone"])
    print("CONFIG_OK")
    print("Policy:", cfg["policy_path"], hashes["policy_sha256"])
    print("Lock:", lock_status(cfg, hashes, now, create=False))
    rc = 0
    upcoming = []
    try:
        transport, rows = acquire_direct_rows(cfg, now, now + timedelta(days=9))
        print(f"{DIRECT_SOURCE_CLASS}: OK ({len(rows)} board games)")
        upcoming = rows
    except DirectSourceFailure as exc:
        print(f"{DIRECT_SOURCE_CLASS}: FAILED {exc} attempts={exc.attempts}")
        rc = 1

    keys = api_keys()
    if not keys:
        print(f"{API_SOURCE_CLASS}: NO_API_KEYS (fallback unavailable)")
    else:
        for slot, key in keys:
            try:
                api_get(f"{cfg['sport_key']}/events",
                        {"commenceTimeFrom": iso_z(now), "commenceTimeTo": iso_z(now + timedelta(days=9)),
                         "dateFormat": "iso"}, keys=[(slot, key)])
                print(f"{API_SOURCE_CLASS} key slot {slot}: OK")
            except CaptureError as exc:
                print(f"{API_SOURCE_CLASS} key slot {slot}: FAILED {exc}")

    local_today = now.astimezone(tz).date()
    for i in range(0, 22):
        d = local_today + timedelta(days=i)
        t = opener_target(d, cfg)
        if WEEKDAYS[d.weekday()] == cfg["opener_weekday"] and t + timedelta(
                minutes=cfg["opener_window_minutes"]) > now and opener_week_for_day(d, cfg) >= cfg["first_week"]:
            print(f"Next opener capture: week {opener_week_for_day(d, cfg)} at {t.isoformat()}")
            break
    lead = timedelta(minutes=cfg["final_minutes_before_kickoff"])
    for row in sorted(upcoming, key=lambda r: r["commence_time"]):
        k = parse_iso(row["commence_time"])
        if week_of(k, cfg) >= cfg["first_week"]:
            print(f"  wk{week_of(k, cfg)} {row['away_team']} @ {row['home_team']}: "
                  f"kickoff {k.astimezone(tz):%a %m-%d %H:%M}, final capture from {(k - lead).astimezone(tz):%H:%M} CT")
    return rc


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "capture"
    now = utc_now()
    try:
        cfg = load_config()
        hashes = current_hashes(cfg)
    except CaptureError as e:
        print(e)
        return 1
    if mode == "check":
        return do_check(cfg, now, hashes)
    rc, captured = 0, False
    for step in (do_opener, do_final):
        try:
            result = step(cfg, now, hashes)
        except CaptureError as e:
            print(f"{step.__name__}: {e}")
            rc = 1
            continue
        if result:
            captured = True
            games = result.get("games") or [g for r in result.get("records", []) for g in r["games"]]
            print(f"{result['capture_kind']}: {len(games)} games, source {result.get('source_class', 'mixed-records')}, lock {result['lock_status']}")
            if result["lock_status"].startswith("MISMATCH"):
                rc = 1
    if not captured and rc == 0:
        print("NO_CAPTURE_DUE")
    return rc


if __name__ == "__main__":
    sys.exit(main())
