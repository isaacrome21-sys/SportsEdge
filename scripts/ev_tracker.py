"""SportsEdge EV tracker (EV_TRACKER_POLICY_V2).

  python scripts/ev_tracker.py log     # from a "[BET]" issue (GitHub Actions)
  python scripts/ev_tracker.py close   # sharp price attempts before start, finalize after start

Exit codes: 0 OK, 3 DEGRADED (handled: key, budget, provider errors), anything else is a crash.
Ledger files are create-only and sealed with a content hash. The API key is never printed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import random
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAYS_DIR = ROOT / "ledger" / "ev_plays"
ATTEMPTS_DIR = ROOT / "ledger" / "ev_close_attempts"
CLOSES_DIR = ROOT / "ledger" / "ev_closes"
SUMMARY = ROOT / "output" / "ev_tracker" / "summary.md"
HEALTH = ROOT / "output" / "ev_tracker" / "health.md"
OK, DEGRADED = 0, 3


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ev = _load("ev_math", "sports/common/ev_math.py")
EVError = ev.EVError


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def provenance(env=None) -> dict:
    env = os.environ if env is None else env
    return {"git_ref": env.get("GITHUB_REF"), "git_sha": env.get("GITHUB_SHA"), "run_id": env.get("GITHUB_RUN_ID")}


# ---------- Odds API ----------

class OddsApiClient:
    BASE = "https://api.the-odds-api.com"
    TRANSIENT = {"ODDS_API_RATE_LIMITED", "ODDS_API_TIMEOUT", "ODDS_API_UNREACHABLE", "ODDS_API_HTTP_5XX"}

    def __init__(self, api_key, reserve, opener=urllib.request.urlopen, sleep=time.sleep, retries=2):
        self.api_key, self.reserve, self.opener, self.sleep, self.retries = api_key, reserve, opener, sleep, retries
        self.remaining = None

    def _once(self, path, params):
        query = urllib.parse.urlencode(dict(params, apiKey=self.api_key))
        req = urllib.request.Request(f"{self.BASE}{path}?{query}", headers={"User-Agent": "SportsEdge-EV-Tracker"})
        try:
            with self.opener(req, timeout=30) as resp:
                left = resp.headers.get("x-requests-remaining")
                raw = resp.read()
            if left is not None:
                self.remaining = int(float(left))
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise EVError("ODDS_API_UNAUTHORIZED") from None
            if exc.code == 429:
                raise EVError("ODDS_API_RATE_LIMITED") from None
            raise EVError("ODDS_API_HTTP_5XX" if exc.code >= 500 else f"ODDS_API_HTTP_{exc.code}") from None
        except (TimeoutError, socket.timeout):
            raise EVError("ODDS_API_TIMEOUT") from None
        except urllib.error.URLError as exc:
            if isinstance(getattr(exc, "reason", None), (TimeoutError, socket.timeout)):
                raise EVError("ODDS_API_TIMEOUT") from None
            raise EVError("ODDS_API_UNREACHABLE") from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise EVError("ODDS_API_BAD_JSON") from None

    def _get(self, path, params, est_cost):
        if est_cost and self.remaining is not None and self.remaining - est_cost < self.reserve:
            raise EVError("BUDGET_RESERVE_REACHED", f"{self.remaining} credits left")
        for attempt in range(self.retries + 1):
            try:
                return self._once(path, params)
            except EVError as exc:
                if exc.code not in self.TRANSIENT or attempt == self.retries:
                    raise
                self.sleep((2 ** attempt) + random.uniform(0, 0.5))

    def check_credits(self):
        self._get("/v4/sports", {}, 0)
        return self.remaining

    def events(self, sport_key):
        data = self._get(f"/v4/sports/{sport_key}/events", {"dateFormat": "iso"}, 0)
        if not isinstance(data, list) or any(
                not isinstance(e, dict) or not all(isinstance(e.get(k), str) for k in ("id", "commence_time", "home_team", "away_team"))
                for e in data):
            raise EVError("ODDS_API_SCHEMA", "events")
        return data

    def event_odds(self, sport_key, event_id, markets, bookmakers):
        regions = max(1, math.ceil(len(bookmakers) / 10))
        data = self._get(
            f"/v4/sports/{sport_key}/events/{event_id}/odds",
            {"markets": ",".join(markets), "bookmakers": ",".join(bookmakers), "oddsFormat": "decimal", "dateFormat": "iso"},
            len(markets) * regions)
        if not isinstance(data, dict) or not isinstance(data.get("bookmakers", []), list):
            raise EVError("ODDS_API_SCHEMA", "event_odds")
        for bk in data.get("bookmakers", []):
            for mk in bk.get("markets", []) if isinstance(bk, dict) else [None]:
                if not isinstance(mk, dict) or not isinstance(mk.get("outcomes", []), list):
                    raise EVError("ODDS_API_SCHEMA", "event_odds markets")
        return data


# ---------- GitHub ----------

class GitHub:
    def __init__(self, token, repo):
        self.token, self.repo = token, repo

    def _call(self, method, path, body):
        req = urllib.request.Request(
            f"https://api.github.com/repos/{self.repo}{path}", method=method, data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json", "User-Agent": "SportsEdge-EV-Tracker"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status

    def comment(self, number, text):
        self._call("POST", f"/issues/{number}/comments", {"body": text})

    def close(self, number):
        self._call("PATCH", f"/issues/{number}", {"state": "closed"})


# ---------- ledger ----------

def read_dir(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(p.read_text()) for p in sorted(path.glob("*.json"))]


def write_new(directory: Path, name: str, record: dict) -> dict:
    """Create-only. An existing record is never overwritten."""
    directory.mkdir(parents=True, exist_ok=True)
    sealed = ev.seal(record)
    try:
        with open(directory / f"{name}.json", "x") as fh:
            fh.write(json.dumps(sealed, indent=2, sort_keys=True) + "\n")
    except FileExistsError:
        raise EVError("LEDGER_RECORD_EXISTS", name) from None
    return sealed


# ---------- log ----------

def parse_issue_body(body: str) -> dict:
    fields, current = {}, None
    for line in (body or "").splitlines():
        if line.startswith("### "):
            current = line[4:].strip()
            fields[current] = []
        elif current is not None:
            fields[current].append(line)
    return {k: ("" if "\n".join(v).strip() == "_No response_" else "\n".join(v).strip()) for k, v in fields.items()}


def _num(text, code):
    try:
        return float(str(text).replace("+", "").strip())
    except ValueError:
        raise EVError(code, str(text)) from None


def build_play(payload: dict, policy: dict, client, env=None) -> dict:
    issue = payload["issue"]
    f = parse_issue_body(issue.get("body", ""))
    sport = policy["sports"].get(f.get("Sport", ""))
    market = policy["markets"].get(f.get("Market", ""))
    book = policy["books"].get(f.get("Book", ""))
    if not sport:
        raise EVError("SPORT_INVALID", f.get("Sport", ""))
    if not market:
        raise EVError("MARKET_INVALID", f.get("Market", ""))
    if not book:
        raise EVError("BOOK_INVALID", f.get("Book", ""))
    price_am = _num(f.get("Price", ""), "PRICE_INVALID")
    price_dec = ev.american_to_decimal(price_am)
    stake = _num(f.get("Stake (units)", ""), "STAKE_INVALID")
    if stake < 0:
        raise EVError("STAKE_INVALID", str(stake))
    tool_ev = _num(f["Tool EV %"], "TOOL_EV_INVALID") if f.get("Tool EV %") else None

    created = ev.parse_utc(issue["created_at"])
    action = payload.get("action", "opened")
    accepted = ev.parse_utc(issue.get("updated_at") or issue["created_at"]) if action == "edited" else created
    events = client.events(sport)
    away_in, home_in, game_date = f.get("Away team", ""), f.get("Home team", ""), f.get("Game date") or None
    try:
        match = ev.match_event(events, away_in, home_in, created, game_date)
    except EVError as exc:
        if exc.code != "EVENT_NOT_FOUND":
            raise
        try:
            ev.match_event(events, away_in, home_in, created - timedelta(days=4), game_date)
        except EVError:
            raise exc from None
        raise EVError("LOGGED_AFTER_START") from None
    event = match["event"]
    start = ev.parse_utc(event["commence_time"])
    if created >= start or accepted >= start:
        raise EVError("LOGGED_AFTER_START")

    raw_pick, raw_line = f.get("Pick", "").strip(), f.get("Line", "").strip()
    line = None
    if market == "totals":
        pick = {"o": "Over", "over": "Over", "u": "Under", "under": "Under"}.get(raw_pick.lower())
        if not pick:
            raise EVError("PICK_INVALID", "use Over or Under")
        line = _num(raw_line, "LINE_INVALID")
        if line <= 0:
            raise EVError("LINE_INVALID", raw_line)
    else:
        teams = [t for t in (event["away_team"], event["home_team"]) if ev.team_matches(raw_pick, t)]
        if len(teams) != 1:
            raise EVError("PICK_INVALID", "pick must name one of the two teams")
        pick = teams[0]
        if market == "spreads":
            line = _num(raw_line, "LINE_INVALID")
        elif raw_line:
            raise EVError("LINE_INVALID", "leave line blank for moneyline")

    return dict(
        provenance(env),
        play_id=f"issue-{issue['number']}", record_type="PLAY",
        policy_id=policy["policy_id"], policy_sha256=policy.get("_sha256"),
        source=f.get("Source") or "Other",
        sport_key=sport, event_id=event["id"], commence_time=event["commence_time"],
        away_team=event["away_team"], home_team=event["home_team"], teams_entered_swapped=match["swapped"],
        market=market, pick=pick, line=line, book=book,
        price_american=int(price_am), price_decimal=round(price_dec, 6), stake_units=stake, tool_ev_pct=tool_ev,
        issue_number=issue["number"], issue_created_at=iso(created), issue_updated_at=issue.get("updated_at"),
        accepted_action=action, accepted_at=iso(accepted),
        accepted_body_sha256=hashlib.sha256((issue.get("body") or "").encode()).hexdigest(),
        slate_date=start.astimezone(ev.CT).date().isoformat(),
    )


def bet_label(p: dict) -> str:
    if p["market"] == "h2h":
        return f"{p['pick']} ML"
    if p["market"] == "spreads":
        return f"{p['pick']} {p['line']:+g}"
    return f"{p['pick']} {p['line']:g} ({p['away_team']} at {p['home_team']})"


def run_log(payload: dict, policy: dict, client, gh, owner: str, env=None) -> str:
    issue = payload.get("issue") or {}
    if not issue.get("title", "").startswith("[BET]"):
        return "SKIP_NOT_BET"
    if (issue.get("user") or {}).get("login") != owner:
        return "SKIP_NOT_OWNER"
    play_id = f"issue-{issue['number']}"
    if (PLAYS_DIR / f"{play_id}.json").exists():
        return "SKIP_ALREADY_LOGGED"
    try:
        play = build_play(payload, policy, client, env)
    except EVError as exc:
        if exc.code.startswith("ODDS_API") or exc.code == "BUDGET_RESERVE_REACHED":
            gh.comment(issue["number"], f"Not logged yet: `{exc.code}` (data provider problem). Edit the issue to retry.")
            return f"DEGRADED_{exc.code}"
        gh.comment(issue["number"], f"Not logged: `{exc}`. Edit the issue to fix it and it will retry.")
        return f"REJECTED_{exc.code}"
    write_new(PLAYS_DIR, play_id, play)
    start_ct = ev.parse_utc(play["commence_time"]).astimezone(ev.CT).strftime("%a %b %-d, %-I:%M %p CT")
    swapped = "\nNote: the book lists these teams the other way around; logged with the book's home/away." if play["teams_entered_swapped"] else ""
    gh.comment(issue["number"],
               f"Logged: **{bet_label(play)}** ({play['away_team']} at {play['home_team']}) at {play['book']} "
               f"{play['price_american']:+d}, {play['stake_units']:g}u. Starts {start_ct}. "
               f"Edits to this issue no longer change the record.{swapped}")
    gh.close(issue["number"])
    return "LOGGED"


# ---------- close ----------

FATAL = {"BUDGET_RESERVE_REACHED", "ODDS_API_UNAUTHORIZED"}
USABLE = ("GRADED", "LINE_ONLY")


def run_close(policy: dict, client, now_fn=utcnow, env=None) -> dict:
    plays = read_dir(PLAYS_DIR)
    finals = {c["play_id"] for c in read_dir(CLOSES_DIR)}
    attempts = {}
    for a in read_dir(ATTEMPTS_DIR):
        attempts.setdefault(a["play_id"], []).append(a)
    cfg = policy["close"]
    sharp_books = sorted(policy["sharp_weights"])
    now = now_fn()
    new_attempts, new_finals = [], []
    result = {"attempted": 0, "finalized": 0, "errors": [], "degraded": False}
    due = {}

    for p in plays:
        if p["play_id"] in finals:
            continue
        start = ev.parse_utc(p["commence_time"])
        mine = sorted(attempts.get(p["play_id"], []), key=lambda a: a["captured_at"])
        if now >= start:
            pre = [a for a in mine if a["status"] in USABLE and ev.parse_utc(a["captured_at"]) < start]
            graded = [a for a in pre if a["status"] == "GRADED"]
            chosen = (graded or pre or [None])[-1]
            final = dict(provenance(env), play_id=p["play_id"], record_type="FINAL_CLOSE",
                         policy_id=policy["policy_id"], selection=cfg["selection"],
                         attempt_count=len(mine), finalized_at=iso(now),
                         last_reason=(mine[-1].get("reason") if mine else "NO_ATTEMPT"))
            if chosen is None:
                final["status"] = "CLOSE_MISSED"
            else:
                final.update({k: v for k, v in chosen.items() if k not in
                              ("content_sha256", "schema_version", "record_type", "git_ref", "git_sha", "run_id", "attempt_id")})
                final["from_attempt"] = chosen["attempt_id"]
            new_finals.append(final)
            continue
        counted = [a for a in mine if a["status"] != "ERROR"]
        if (start - now).total_seconds() / 60 <= cfg["window_minutes"] and len(counted) < cfg["max_attempts"]:
            due.setdefault((p["sport_key"], p["event_id"]), []).append((p, len(mine)))

    stop = None
    for (sport, event_id), group in due.items():
        fetched = now_fn()
        if stop is None:
            try:
                odds = client.event_odds(sport, event_id, sorted({p["market"] for p, _ in group}), sharp_books)
            except EVError as exc:
                odds, err = None, exc.code
                result["errors"].append(exc.code)
                if exc.code in FATAL:
                    stop = exc.code
        else:
            odds, err = None, stop
        for p, n_prev in group:
            base = dict(provenance(env), attempt_id=f"{p['play_id']}-a{n_prev + 1}", play_id=p["play_id"],
                        record_type="CLOSE_ATTEMPT", policy_id=policy["policy_id"], captured_at=iso(fetched),
                        minutes_before_start=round((ev.parse_utc(p["commence_time"]) - fetched).total_seconds() / 60, 1))
            if odds is None:
                base.update(status="ERROR", reason=err)
            else:
                base.update(ev.grade_attempt(odds, p, policy, fetched))
            new_attempts.append(base)
            result["attempted"] += 1

    for a in new_attempts:
        write_new(ATTEMPTS_DIR, a["attempt_id"], a)
    for f in new_finals:
        write_new(CLOSES_DIR, f["play_id"], f)
        result["finalized"] += 1
    result["degraded"] = bool(result["errors"])
    return result


# ---------- summary ----------

def render_summary(policy: dict, now: datetime) -> str:
    plays = read_dir(PLAYS_DIR)
    finals = {c["play_id"]: c for c in read_dir(CLOSES_DIR)}
    ref, pid = policy["evidence_ref"], policy["policy_id"]
    evidence = [p for p in plays if p.get("policy_id") == pid and p.get("git_ref") == ref]
    other = len(plays) - len(evidence)

    lines = ["# SportsEdge EV Tracker (derived report, not evidence)", "",
             "Your picks from outside +EV tools, graded by CLV against sharp prices before start.",
             "MARKET_FAIR_P only · NOT Model_P · NOT Truth Gate · NOT OFFICIAL", "",
             f"Updated {now.astimezone(ev.CT).strftime('%b %-d, %-I:%M %p CT')} · Policy {pid}", "",
             "## Bet size by source and sport", "",
             "| Your picks from | Sport | Stage | Bet size | Logged | Started | Graded | Coverage | Avg CLV | 97.5% low | Avg line move |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    sport_names = {v: k for k, v in policy["sports"].items()}
    buckets = {}
    for p in evidence:
        buckets.setdefault((p["source"], p["sport_key"]), []).append(p)
    if not buckets:
        s = policy["staging"]["start"]
        lines.append(f"| (none yet) | — | {s} | {policy['staging']['units'][s]:g}u | 0 | 0 | 0 | — | — | — | — |")
    for source, sport_key in sorted(buckets):
        group = buckets[(source, sport_key)]
        started = [p for p in group if ev.parse_utc(p["commence_time"]) <= now]
        rows, moves = [], []
        for p in started:
            f = finals.get(p["play_id"])
            if f and f.get("git_ref") == ref and f["status"] == "GRADED":
                rows.append({"slate_date": p["slate_date"], "clv_pp": f["prob_clv_pp"]})
            if f and f.get("line_clv_pts") is not None and p["market"] != "h2h":
                moves.append(f["line_clv_pts"])
        st = ev.source_stage(rows, len(started), policy["staging"], sport_key)
        fmt = lambda v, spec: "—" if v is None else format(v, spec)
        lines.append(
            f"| {source} | {sport_names.get(sport_key, sport_key)} | {st['stage']}{' (cap)' if st['capped_by'] else ''} | "
            f"{st['units']:g}u | {len(group)} | {len(started)} | {st['graded']} | "
            f"{fmt(None if st['coverage'] is None else 100 * st['coverage'], '.0f')}{'%' if st['coverage'] is not None else ''} | "
            f"{fmt(st['mean_clv_pp'], '+.2f')}{'pp' if st['mean_clv_pp'] is not None else ''} | "
            f"{fmt(st['lower_bound_pp'], '+.2f')}{'pp' if st['lower_bound_pp'] is not None else ''} | "
            f"{fmt(sum(moves) / len(moves) if moves else None, '+.2f')}{' pts' if moves else ''} |")
    if other:
        lines += ["", f"{other} older or non-main plays are kept in the ledger but are not {pid} evidence."]

    lines += ["", "## Recent plays", "", "| Game day | Bet | Book | Price | CLV |", "|---|---|---|---|---|"]
    recent = sorted(evidence, key=lambda p: p["accepted_at"], reverse=True)[:15]
    if not recent:
        lines.append("| — | No plays logged yet | — | — | — |")
    for p in recent:
        f = finals.get(p["play_id"])
        if f is None:
            clv = "pending"
        elif f["status"] == "GRADED":
            tag = "" if f.get("prob_clv_method") == "SAME_LINE" else " (line-adjusted)"
            clv = f"{f['prob_clv_pp']:+.2f}pp{tag}"
        elif f["status"] == "LINE_ONLY":
            clv = f"line {f['line_clv_pts']:+g} pts"
        else:
            clv = f"missed ({f.get('last_reason')})"
        lines.append(f"| {p['slate_date']} | {bet_label(p)} | {p['book']} | {p['price_american']:+d} | {clv} |")
    lines += ["", "## Before you take a play", ""] + [f"- {r}" for r in policy["take_rules"]]
    return "\n".join(lines) + "\n"


def _without_timestamp(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not l.startswith("Updated "))


def write_if_changed(path: Path, text: str) -> bool:
    if path.exists() and _without_timestamp(path.read_text()) == _without_timestamp(text):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return True


def write_health(now, status, detail, credits=None):
    write_if_changed(HEALTH, "\n".join([
        "# EV Tracker health", "",
        f"Updated {now.astimezone(ev.CT).strftime('%b %-d, %-I:%M %p CT')}",
        f"Status: {status}", f"Detail: {detail}",
        f"Odds API credits left: {'unknown' if credits is None else credits}", ""]))


# ---------- entry ----------

def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    mode = argv[0] if argv else "close"
    policy = ev.load_active_policy(ROOT)
    key = os.environ.get("ODDS_API_KEY", "")

    if mode == "log":
        payload = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        gh = GitHub(os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"])
        if not key:
            if (payload.get("issue") or {}).get("number"):
                gh.comment(payload["issue"]["number"], "Not logged yet: the `SPORTSEDGE_ODDS_API_KEY` secret is missing.")
            return DEGRADED
        outcome = run_log(payload, policy, OddsApiClient(key, policy["budget"]["reserve_credits"]),
                          gh, os.environ.get("GITHUB_REPOSITORY_OWNER", ""))
        print(outcome)
        return DEGRADED if outcome.startswith("DEGRADED_") else OK

    if mode == "close":
        now = utcnow()
        if not key:
            write_health(now, "DEGRADED", "BLOCKED_NO_API_KEY")
            write_if_changed(SUMMARY, render_summary(policy, now))
            return DEGRADED
        client = OddsApiClient(key, policy["budget"]["reserve_credits"])
        try:
            client.check_credits()
        except EVError as exc:
            write_health(now, "DEGRADED", exc.code)
            return DEGRADED
        result = run_close(policy, client)
        write_health(utcnow(), "DEGRADED" if result["degraded"] else "OK",
                     json.dumps(result, sort_keys=True), client.remaining)
        write_if_changed(SUMMARY, render_summary(policy, utcnow()))
        print(json.dumps(result, sort_keys=True))
        return DEGRADED if result["degraded"] else OK

    print(f"unknown mode {mode}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
