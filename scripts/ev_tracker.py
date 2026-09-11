"""SportsEdge EV tracker.

  python scripts/ev_tracker.py log     # from a "[BET]" issue (GitHub Actions)
  python scripts/ev_tracker.py close   # capture sharp prices before start, refresh summary

One JSON file per play and per close, so parallel runs never conflict.
The API key is never printed.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAYS_DIR = ROOT / "ledger" / "ev_plays"
CLOSES_DIR = ROOT / "ledger" / "ev_closes"
SUMMARY = ROOT / "output" / "ev_tracker" / "summary.md"
POLICY_PATH = ROOT / "config" / "ev_tracker_policy_v1.json"


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


# ---------- Odds API ----------

class OddsApiClient:
    BASE = "https://api.the-odds-api.com"

    def __init__(self, api_key: str, reserve: int, opener=urllib.request.urlopen):
        self.api_key, self.reserve, self.opener = api_key, reserve, opener
        self.remaining = None

    def _get(self, path, params, est_cost):
        if est_cost and self.remaining is not None and self.remaining - est_cost < self.reserve:
            raise EVError("BUDGET_RESERVE_REACHED", f"{self.remaining} credits left")
        query = urllib.parse.urlencode(dict(params, apiKey=self.api_key))
        req = urllib.request.Request(f"{self.BASE}{path}?{query}", headers={"User-Agent": "SportsEdge-EV-Tracker"})
        try:
            with self.opener(req, timeout=30) as resp:
                left = resp.headers.get("x-requests-remaining")
                if left is not None:
                    self.remaining = int(float(left))
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            code = {401: "ODDS_API_UNAUTHORIZED", 429: "ODDS_API_RATE_LIMITED"}.get(exc.code, f"ODDS_API_HTTP_{exc.code}")
            raise EVError(code) from None
        except urllib.error.URLError:
            raise EVError("ODDS_API_UNREACHABLE") from None

    def check_credits(self):
        self._get("/v4/sports", {}, 0)
        return self.remaining

    def events(self, sport_key):
        return self._get(f"/v4/sports/{sport_key}/events", {"dateFormat": "iso"}, 0)

    def event_odds(self, sport_key, event_id, markets, bookmakers):
        regions = max(1, math.ceil(len(bookmakers) / 10))
        return self._get(
            f"/v4/sports/{sport_key}/events/{event_id}/odds",
            {"markets": ",".join(markets), "bookmakers": ",".join(bookmakers),
             "oddsFormat": "decimal", "dateFormat": "iso"},
            len(markets) * regions,
        )


# ---------- GitHub ----------

class GitHub:
    def __init__(self, token, repo):
        self.token, self.repo = token, repo

    def _call(self, method, path, body):
        req = urllib.request.Request(
            f"https://api.github.com/repos/{self.repo}{path}", method=method,
            data=json.dumps(body).encode(), headers={
                "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
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


def write_record(path: Path, record: dict):
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{record['play_id']}.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


# ---------- log ----------

def parse_issue_body(body: str) -> dict:
    fields, current = {}, None
    for line in (body or "").splitlines():
        if line.startswith("### "):
            current = line[4:].strip()
            fields[current] = []
        elif current is not None:
            fields[current].append(line)
    out = {}
    for k, lines in fields.items():
        val = "\n".join(lines).strip()
        out[k] = "" if val == "_No response_" else val
    return out


def _num(text, code):
    try:
        return float(str(text).replace("+", "").strip())
    except ValueError:
        raise EVError(code, str(text)) from None


def build_play(issue: dict, policy: dict, client, now: datetime, current_stage_units: float = None) -> dict:
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
    game_date = f.get("Game date") or None

    logged_at = ev.parse_utc(issue["created_at"])
    events = client.events(sport)
    away_in, home_in = f.get("Away team", ""), f.get("Home team", "")
    try:
        match = ev.match_event(events, away_in, home_in, logged_at, game_date)
    except EVError as exc:
        if exc.code != "EVENT_NOT_FOUND":
            raise
        try:
            ev.match_event(events, away_in, home_in, logged_at - timedelta(days=4), game_date)
        except EVError:
            raise exc from None
        raise EVError("LOGGED_AFTER_START") from None
    event = match["event"]
    start = ev.parse_utc(event["commence_time"])
    if logged_at >= start:
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

    return {
        "play_id": f"issue-{issue['number']}",
        "policy_id": policy["policy_id"], "policy_sha256": policy.get("_sha256"),
        "source": f.get("Source", "Other") or "Other",
        "sport_key": sport, "event_id": event["id"], "commence_time": event["commence_time"],
        "away_team": event["away_team"], "home_team": event["home_team"],
        "teams_entered_swapped": match["swapped"],
        "market": market, "pick": pick, "line": line, "book": book,
        "price_american": int(price_am), "price_decimal": round(price_dec, 6),
        "stake_units": stake, "tool_ev_pct": tool_ev,
        "logged_at": iso(logged_at), "slate_date": start.astimezone(ev.CT).date().isoformat(),
    }


def bet_label(p: dict) -> str:
    if p["market"] == "h2h":
        return f"{p['pick']} ML"
    if p["market"] == "spreads":
        return f"{p['pick']} {p['line']:+g}"
    return f"{p['pick']} {p['line']:g} ({p['away_team']} at {p['home_team']})"


def run_log(event_payload: dict, policy: dict, client, gh, owner: str) -> str:
    issue = event_payload.get("issue") or {}
    if not issue.get("title", "").startswith("[BET]"):
        return "SKIP_NOT_BET"
    if (issue.get("user") or {}).get("login") != owner:
        return "SKIP_NOT_OWNER"
    play_id = f"issue-{issue['number']}"
    if (PLAYS_DIR / f"{play_id}.json").exists():
        return "SKIP_ALREADY_LOGGED"
    try:
        play = build_play(issue, policy, client, utcnow())
    except EVError as exc:
        gh.comment(issue["number"], f"Not logged: `{exc}`. Edit the issue to fix it and it will retry.")
        return f"REJECTED_{exc.code}"
    write_record(PLAYS_DIR, play)
    start_ct = ev.parse_utc(play["commence_time"]).astimezone(ev.CT).strftime("%a %b %-d, %-I:%M %p CT")
    swapped = "\nNote: the book lists these teams the other way around; logged with the book's home/away." if play["teams_entered_swapped"] else ""
    gh.comment(issue["number"],
               f"Logged: **{bet_label(play)}** at {play['book']} {play['price_american']:+d}, "
               f"{play['stake_units']:g}u. Game starts {start_ct}. "
               f"It will be graded against the sharp price before start.{swapped}")
    gh.close(issue["number"])
    return "LOGGED"


# ---------- close ----------

def run_close(policy: dict, client, now_fn=utcnow) -> dict:
    plays = read_dir(PLAYS_DIR)
    done = {c["play_id"] for c in read_dir(CLOSES_DIR)}
    window = policy["close"]["window_minutes"]
    sharp_books = sorted(policy["sharp_weights"])
    now = now_fn()
    result = {"captured": 0, "missed": 0, "unavailable": 0, "errors": []}
    due = {}
    for p in plays:
        if p["play_id"] in done:
            continue
        mins = (ev.parse_utc(p["commence_time"]) - now).total_seconds() / 60
        if mins <= 0:
            write_record(CLOSES_DIR, {"play_id": p["play_id"], "status": "CLOSE_MISSED", "captured_at": iso(now)})
            result["missed"] += 1
        elif mins <= window:
            due.setdefault((p["sport_key"], p["event_id"]), []).append(p)
    for (sport, event_id), group in due.items():
        markets = sorted({p["market"] for p in group})
        try:
            odds = client.event_odds(sport, event_id, markets, sharp_books)
        except EVError as exc:
            result["errors"].append(exc.code)
            if exc.code in ("BUDGET_RESERVE_REACHED", "ODDS_API_UNAUTHORIZED"):
                break
            continue
        fetched = now_fn()
        for p in group:
            fair = ev.sharp_fair_for_play(odds, p, policy, fetched)
            rec = {"play_id": p["play_id"], "captured_at": iso(fetched),
                   "close_type": policy["close"]["close_type"],
                   "minutes_before_start": round((ev.parse_utc(p["commence_time"]) - fetched).total_seconds() / 60, 1)}
            if fair["status"] == "OK":
                rec.update(status="GRADED", close_fair_p=round(fair["fair_p"], 6),
                           sharp_books=sorted(fair["books"]),
                           clv_pp=round(ev.clv_pp(p["price_decimal"], fair["fair_p"]), 3))
                result["captured"] += 1
            else:
                rec.update(status="CLOSE_UNAVAILABLE", reason=fair["reason"])
                result["unavailable"] += 1
            write_record(CLOSES_DIR, rec)
    return result


# ---------- summary ----------

def render_summary(policy: dict, now: datetime, credits=None, status_note: str = "") -> str:
    plays = {p["play_id"]: p for p in read_dir(PLAYS_DIR)}
    closes = {c["play_id"]: c for c in read_dir(CLOSES_DIR)}
    by_source = {}
    for pid, p in plays.items():
        by_source.setdefault(p["source"], []).append(p)

    lines = [
        "# SportsEdge EV Tracker",
        "",
        "Outside +EV plays, graded by CLV against the sharp price before start.",
        "MARKET_FAIR_P only · NOT Model_P · NOT Truth Gate · NOT OFFICIAL",
        "",
        f"Updated {now.astimezone(ev.CT).strftime('%b %-d, %-I:%M %p CT')}"
        + (f" · Odds API credits left: {credits}" if credits is not None else ""),
    ]
    if status_note:
        lines += ["", f"**Status:** {status_note}"]
    lines += ["", "## Stake by source", "",
              "| Source | Stage | Bet size | Logged | Graded | Avg CLV | t |",
              "|---|---|---|---|---|---|---|"]
    if not by_source:
        lines.append(f"| (none yet) | {policy['staging']['start']} | "
                     f"{policy['staging']['units'][policy['staging']['start']]:g}u | 0 | 0 | — | — |")
    for source in sorted(by_source):
        graded = [dict(clv_pp=closes[p["play_id"]]["clv_pp"], slate_date=p["slate_date"])
                  for p in by_source[source]
                  if closes.get(p["play_id"], {}).get("status") == "GRADED"]
        st = ev.source_stage(graded, policy["staging"])
        mean = "—" if st["mean_clv_pp"] is None else f"{st['mean_clv_pp']:+.2f}pp"
        t = "—" if st["clv_t_stat"] is None else f"{st['clv_t_stat']:.2f}"
        lines.append(f"| {source} | {st['stage']} | {st['units']:g}u | {len(by_source[source])} | "
                     f"{st['graded']} | {mean} | {t} |")

    lines += ["", "## Recent plays", "", "| Game day | Bet | Book | Price | CLV |", "|---|---|---|---|---|"]
    recent = sorted(plays.values(), key=lambda p: p["logged_at"], reverse=True)[:15]
    if not recent:
        lines.append("| — | No plays logged yet | — | — | — |")
    for p in recent:
        c = closes.get(p["play_id"])
        if c is None:
            clv = "pending"
        elif c["status"] == "GRADED":
            clv = f"{c['clv_pp']:+.2f}pp"
        elif c["status"] == "CLOSE_MISSED":
            clv = "missed"
        else:
            clv = f"n/a ({c.get('reason', '')})"
        lines.append(f"| {p['slate_date']} | {bet_label(p)} | {p['book']} | {p['price_american']:+d} | {clv} |")

    lines += ["", "## Before you take a play", ""] + [f"- {r}" for r in policy["take_rules"]]
    return "\n".join(lines) + "\n"


def _without_timestamp(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not l.startswith("Updated "))


def write_summary(text: str) -> bool:
    """Writes only when content other than the Updated line changed, so quiet runs make no commit."""
    if SUMMARY.exists() and _without_timestamp(SUMMARY.read_text()) == _without_timestamp(text):
        return False
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(text)
    return True


# ---------- entry ----------

def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    mode = argv[0] if argv else "close"
    policy = ev.load_policy(POLICY_PATH)
    key = os.environ.get("ODDS_API_KEY", "")

    if mode == "log":
        payload = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        gh = GitHub(os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"])
        if not key:
            number = (payload.get("issue") or {}).get("number")
            if number:
                gh.comment(number, "Not logged: the `SPORTSEDGE_ODDS_API_KEY` secret is missing.")
            return 2
        client = OddsApiClient(key, policy["budget"]["reserve_credits"])
        outcome = run_log(payload, policy, client, gh, os.environ.get("GITHUB_REPOSITORY_OWNER", ""))
        print(outcome)
        return 2 if outcome.startswith("REJECTED_ODDS_API") else 0

    if mode == "close":
        if not key:
            write_summary(render_summary(policy, utcnow(), status_note="BLOCKED_NO_API_KEY"))
            print("BLOCKED_NO_API_KEY")
            return 2
        client = OddsApiClient(key, policy["budget"]["reserve_credits"])
        try:
            client.check_credits()
        except EVError as exc:
            write_summary(render_summary(policy, utcnow(), status_note=f"BLOCKED {exc.code}"))
            print(exc.code)
            return 2
        result = run_close(policy, client)
        note = "OK" if not result["errors"] else "ERRORS " + ", ".join(sorted(set(result["errors"])))
        write_summary(render_summary(policy, utcnow(), client.remaining, note))
        print(json.dumps(result))
        return 2 if result["errors"] else 0

    print(f"unknown mode {mode}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
