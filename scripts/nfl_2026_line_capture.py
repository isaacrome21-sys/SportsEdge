#!/usr/bin/env python3
"""NFL 2026 confirmation line capture (DraftKings spreads + totals).

Rules enforced here:
- OPENER: first successful capture at/after the frozen local time on the frozen
  weekday, inside the opener window. Target week = window starting on the first
  Tuesday on/after the capture date.
- FINAL: first successful capture at/after kickoff minus the frozen lead, inside
  the final window, and always before kickoff.
- No backfills: nothing is ever captured outside those windows, whatever triggered
  the run. Existing capture files are never overwritten.
- Policy file, this config, this script and the workflow are hash-locked at the
  first capture. Any later change is still captured but flagged MISMATCH and the
  job fails visibly.
Standard library only.
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

API = "https://api.the-odds-api.com/v4/sports"
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
ALLOWED_OPENER_DAYS = {"Sunday", "Monday", "Tuesday"}
CONFIG_PATH = os.environ.get("CAPTURE_CONFIG", "config/nfl_2026_capture.json")


class CaptureError(Exception):
    pass


def utc_now():
    return datetime.now(timezone.utc)


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def iso_z(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


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
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(json.dumps({**hashes, "locked_at_utc": now.isoformat()}, indent=2))
        return "LOCK_CREATED"
    saved = json.loads(lock.read_text())
    diffs = [k for k in hashes if saved.get(k) != hashes[k]]
    return "MATCH" if not diffs else "MISMATCH:" + ",".join(diffs)


# ---------- API ----------

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


# ---------- normalization ----------

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
               "book": cfg["bookmaker"]}
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


# ---------- capture steps ----------

def run_meta():
    return {k.lower(): os.environ.get(k) for k in
            ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA", "GITHUB_EVENT_NAME")}


def log_attempt(cfg, entry):
    path = Path(cfg["output_dir"]) / "attempts.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def write_new(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise CaptureError(f"REFUSING_OVERWRITE {path}")
    path.write_text(json.dumps(record, indent=2))


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


def do_opener(cfg, now, hashes):
    due = opener_due(now, cfg)
    if not due:
        return None
    path = Path(cfg["output_dir"]) / f"week{due['week']:02d}" / "opener.json"
    if path.exists():
        return None
    try:
        ws, we = week_bounds_utc(due["week"], cfg)
        t_from = max(ws, now)
        events = api_get(f"{cfg['sport_key']}/events",
                         {"commenceTimeFrom": iso_z(t_from), "commenceTimeTo": iso_z(we), "dateFormat": "iso"})
        odds = api_get(f"{cfg['sport_key']}/odds", odds_params(cfg, t_from, we))
    except CaptureError as e:
        log_attempt(cfg, {"run_started_utc": now.isoformat(), "kind": "OPENER", "week": due["week"],
                          "outcome": str(e), **run_meta()})
        raise
    retrieved = parse_iso(odds["received_at_utc"])
    status = lock_status(cfg, hashes, now, create=True)
    record = {
        "capture_kind": "OPENER", "week": due["week"], "book": cfg["bookmaker"], "markets": cfg["markets"],
        "target_local": due["target"].isoformat(), "run_started_utc": now.isoformat(),
        "retrieved_at_utc": odds["received_at_utc"],
        "minutes_after_target": round((retrieved - due["target"]).total_seconds() / 60, 2),
        "lock_status": status, "hashes": hashes, "run": run_meta(),
        "predictions_at_opener": predictions_status(cfg, due["week"]),
        "api": {k: {x: v[x] for x in ("key_slot", "quota", "failed_key_slots", "raw_sha256", "received_at_utc")}
                for k, v in (("events", events), ("odds", odds))},
        "games": game_rows(events["data"], odds["data"], cfg),
        "raw_events": events["data"], "raw_odds": odds["data"],
    }
    write_new(path, record)
    return record


def captured_final_ids(cfg):
    ids = set()
    for p in Path(cfg["output_dir"]).glob("week*/final/*.json"):
        ids.update(g["event_id"] for g in json.loads(p.read_text())["games"])
    return ids


def do_final(cfg, now, hashes):
    lead = timedelta(minutes=cfg["final_minutes_before_kickoff"])
    window = timedelta(minutes=cfg["final_window_minutes"])
    events = api_get(f"{cfg['sport_key']}/events",
                     {"commenceTimeFrom": iso_z(now), "commenceTimeTo": iso_z(now + lead + timedelta(minutes=1)),
                      "dateFormat": "iso"})
    done = captured_final_ids(cfg)
    due = []
    for ev in events["data"]:
        kickoff = parse_iso(ev["commence_time"])
        if ev["id"] in done or week_of(kickoff, cfg) < cfg["first_week"]:
            continue
        if kickoff - lead <= now < min(kickoff - lead + window, kickoff):
            due.append(ev)
    if not due:
        return None
    kicks = [parse_iso(e["commence_time"]) for e in due]
    try:
        odds = api_get(f"{cfg['sport_key']}/odds",
                       odds_params(cfg, min(kicks), max(kicks) + timedelta(minutes=1)))
    except CaptureError as e:
        log_attempt(cfg, {"run_started_utc": now.isoformat(), "kind": "FINAL",
                          "event_ids": [e2["id"] for e2 in due], "outcome": str(e), **run_meta()})
        raise
    retrieved = parse_iso(odds["received_at_utc"])
    rows = game_rows(due, odds["data"], cfg, wanted_ids={e["id"] for e in due})
    for r in rows:
        kickoff = parse_iso(r["commence_time"])
        r["target_utc"] = (kickoff - lead).isoformat()
        r["minutes_before_kickoff"] = round((kickoff - retrieved).total_seconds() / 60, 2)
        if retrieved >= kickoff:
            r["capture_validity"] = "AFTER_KICKOFF_INVALID"
    status = lock_status(cfg, hashes, now, create=True)
    written = []
    for week in sorted({r["week"] for r in rows}):
        stamp = retrieved.strftime("%Y%m%dT%H%M%SZ")
        record = {
            "capture_kind": "FINAL", "week": week, "book": cfg["bookmaker"], "markets": cfg["markets"],
            "run_started_utc": now.isoformat(), "retrieved_at_utc": odds["received_at_utc"],
            "lock_status": status, "hashes": hashes, "run": run_meta(),
            "api": {"odds": {x: odds[x] for x in ("key_slot", "quota", "failed_key_slots", "raw_sha256")}},
            "games": [r for r in rows if r["week"] == week],
            "raw_odds": odds["data"],
        }
        write_new(Path(cfg["output_dir"]) / f"week{week:02d}" / "final" / f"{stamp}.json", record)
        written.append(record)
    return {"capture_kind": "FINAL", "lock_status": status, "records": written}


# ---------- check mode ----------

def do_check(cfg, now, hashes):
    tz = ZoneInfo(cfg["timezone"])
    print("CONFIG_OK")
    print("Policy:", cfg["policy_path"], hashes["policy_sha256"])
    print("Lock:", lock_status(cfg, hashes, now, create=False))
    keys = api_keys()
    if not keys:
        print("NO_API_KEYS")
        return 1
    rc = 0
    upcoming = None
    for slot, key in keys:
        try:
            res = api_get(f"{cfg['sport_key']}/events",
                          {"commenceTimeFrom": iso_z(now), "commenceTimeTo": iso_z(now + timedelta(days=9)),
                           "dateFormat": "iso"}, keys=[(slot, key)])
            print(f"Key slot {slot}: OK (events endpoint is free)")
            upcoming = upcoming or res["data"]
        except CaptureError as e:
            print(f"Key slot {slot}: FAILED {e}")
            rc = 1
    local_today = now.astimezone(tz).date()
    for i in range(0, 22):
        d = local_today + timedelta(days=i)
        t = opener_target(d, cfg)
        if WEEKDAYS[d.weekday()] == cfg["opener_weekday"] and t + timedelta(
                minutes=cfg["opener_window_minutes"]) > now and opener_week_for_day(d, cfg) >= cfg["first_week"]:
            print(f"Next opener capture: week {opener_week_for_day(d, cfg)} at {t.isoformat()}")
            break
    lead = timedelta(minutes=cfg["final_minutes_before_kickoff"])
    for ev in sorted(upcoming or [], key=lambda e: e["commence_time"]):
        k = parse_iso(ev["commence_time"])
        if week_of(k, cfg) >= cfg["first_week"]:
            print(f"  wk{week_of(k, cfg)} {ev['away_team']} @ {ev['home_team']}: "
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
            print(f"{result['capture_kind']}: {len(games)} games, lock {result['lock_status']}")
            if result["lock_status"].startswith("MISMATCH"):
                rc = 1
    if not captured and rc == 0:
        print("NO_CAPTURE_DUE")
    return rc


if __name__ == "__main__":
    sys.exit(main())
