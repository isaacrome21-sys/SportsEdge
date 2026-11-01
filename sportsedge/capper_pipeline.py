"""CAPPER_VETTER_V1 pipeline: [CAPPER] issues -> pick records -> closes ->
results -> ranked table.

Pure functions only (no network, no GitHub); the runner
``scripts/run_capper_vetter.py`` does the I/O. Steps:

  1. parse_issue()       "[CAPPER]" issue-form body -> pick record
  2. match_event()       pick -> ESPN scoreboard event (teams + date)
     attach_close()      close price/line from the event's DK close odds,
                         or an owner/Muse override comment "close: -125 / +105"
  3. settle()            final score -> win / loss / push (spread, total,
                         moneyline, team total); props need a comment
                         "result: win|loss|push"
  4. render_table()      ranked markdown for the tracker issue

Writes nothing to the repository (freeze-reconciliation hold); output is a
workflow artifact plus an issue comment.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")

ESPN_PATHS = {
    "NCAAB": ("basketball/mens-college-basketball", "50"),
    "NCAAF": ("football/college-football", "80"),
    "NFL": ("football/nfl", None),
    "NBA": ("basketball/nba", None),
    "NHL": ("hockey/nhl", None),
    "MLB": ("baseball/mlb", None),
}

_FIELD_MAP = {
    "Account": "account", "Other account handle": "other_account",
    "Posted at (Central)": "posted_at_ct", "Post link": "post_url",
    "Sport": "sport", "Game (Away @ Home)": "game", "Market": "market",
    "Pick": "selection", "Line": "line", "Price when posted": "price",
    "Units (if the account gives them)": "units",
    "Does this account post its losses?": "shows_losses",
}

_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")


class PickParseError(ValueError):
    pass


# ---------------------------------------------------------------- step 1
def _form_fields(body: str) -> dict:
    out, label, buf = {}, None, []
    for line in (body or "").splitlines():
        m = re.match(r"^###\s+(.*)$", line)
        if m:
            if label:
                out[label] = "\n".join(buf).strip()
            label, buf = m.group(1).strip(), []
        elif label:
            buf.append(line)
    if label:
        out[label] = "\n".join(buf).strip()
    return {k: ("" if v == "_No response_" else v) for k, v in out.items()}


def _num(text, *, required=False, name=""):
    m = _NUM.search(str(text or "").replace("½", ".5"))
    if not m:
        if required:
            raise PickParseError(f"{name} missing or not a number: {text!r}")
        return None
    return float(m.group(0))


def parse_posted_at(text: str) -> datetime:
    text = (text or "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M %p", "%Y-%m-%d %I:%M%p",
                "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p", "%m/%d %I:%M %p"):
        try:
            dt = datetime.strptime(text.upper() if "%p" in fmt else text, fmt)
            if dt.year == 1900:
                dt = dt.replace(year=datetime.now(CT).year)
            return dt.replace(tzinfo=CT)
        except ValueError:
            continue
    raise PickParseError(f"posted-at time not understood: {text!r} (use 2026-11-01 17:30)")


def parse_issue(number: int, title: str, body: str, created_at: str | None = None,
                comments: list[str] | None = None) -> dict:
    f = {(_FIELD_MAP.get(k) or k): v for k, v in _form_fields(body).items()}
    account = f.get("account", "")
    if account == "Other":
        account = f.get("other_account", "").strip()
    if not account:
        raise PickParseError("account missing")
    if not account.startswith("@"):
        account = "@" + account
    game = f.get("game", "")
    parts = re.split(r"\s+(?:@|at|vs\.?|v)\s+", game, maxsplit=1, flags=re.I)
    if len(parts) != 2:
        raise PickParseError(f"game must be 'Away @ Home': {game!r}")
    price = _num(f.get("price"), required=True, name="price")
    if -100 < price < 100:
        raise PickParseError(f"price must be American odds: {price}")
    posted = parse_posted_at(f.get("posted_at_ct", ""))
    if created_at:
        filed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if posted > filed + timedelta(minutes=5):
            raise PickParseError("posted-at is later than the issue itself")
    shows = {"Yes": True, "No": False}.get(f.get("shows_losses", ""), None)
    pick = {
        "issue": number, "account": account, "post_url": f.get("post_url") or None,
        "posted_at": posted.isoformat(), "sport": f.get("sport", "").upper(),
        "away": parts[0].strip(), "home": parts[1].strip(),
        "market": f.get("market", ""), "selection": f.get("selection", "").strip(),
        "line": _num(f.get("line")), "price": int(price),
        "units": _num(f.get("units")) or 1.0, "shows_losses": shows,
        "result": "pending",
    }
    if pick["sport"] not in ESPN_PATHS:
        raise PickParseError(f"sport not supported: {pick['sport']!r}")
    if pick["market"] in ("Spread", "Total", "1H Spread", "1H Total", "Team Total") and pick["line"] is None:
        raise PickParseError(f"{pick['market']} pick needs a line")
    apply_comments(pick, comments or [])
    return pick


def apply_comments(pick: dict, comments: list[str]) -> None:
    """Latest override wins: 'close: -125 / +105' (pick side / other side,
    optional 'line 154.5'), 'result: win|loss|push', 'void'."""
    for c in comments:
        t = c.strip().lower()
        m = re.search(r"close:\s*([-+]?\d{3,})\s*(?:/\s*([-+]?\d{3,}))?(?:.*?line\s*([-+]?\d+(?:\.\d+)?))?", t)
        if m:
            pick["close_price"] = int(m.group(1))
            pick["close_other_price"] = int(m.group(2)) if m.group(2) else None
            if m.group(3):
                pick["close_line"] = float(m.group(3))
            pick["close_source"] = "COMMENT"
        m = re.search(r"result:\s*(win|loss|push)", t)
        if m:
            pick["result"] = m.group(1)
            pick["result_source"] = "COMMENT"
        if re.search(r"^\s*void\b", t):
            pick["void"] = True


# ---------------------------------------------------------------- step 2
def _norm(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
    s = re.sub(r"\bst\b", "state", s)
    return re.sub(r"\s+", " ", s).strip()


def _team_names(comp_team: dict) -> set[str]:
    t = comp_team.get("team", {})
    return {_norm(t.get(k, "")) for k in
            ("displayName", "shortDisplayName", "location", "name", "abbreviation", "nickname")} - {""}


def _team_hit(user: str, comp_team: dict) -> bool:
    u = _norm(user)
    names = _team_names(comp_team)
    return u in names or any(n and (u == n or (len(u) >= 4 and n.startswith(u))
                                    or (len(n) >= 4 and u.startswith(n))) for n in names)


def match_event(pick: dict, events: list[dict]) -> dict | None:
    """Earliest event at/after the post date whose away/home match."""
    hits = []
    for ev in events:
        comp = (ev.get("competitions") or [{}])[0]
        teams = comp.get("competitors") or []
        away = next((c for c in teams if c.get("homeAway") == "away"), None)
        home = next((c for c in teams if c.get("homeAway") == "home"), None)
        if not away or not home:
            continue
        straight = _team_hit(pick["away"], away) and _team_hit(pick["home"], home)
        flipped = _team_hit(pick["away"], home) and _team_hit(pick["home"], away)
        if straight or (flipped and comp.get("neutralSite")):
            hits.append(ev)
    hits.sort(key=lambda e: e.get("date", ""))
    return hits[0] if hits else None


def event_tip(ev: dict) -> datetime:
    return datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))


def _side(pick: dict, ev: dict) -> str:
    """'home' | 'away' | 'over' | 'under' for the picked selection."""
    sel = _norm(pick["selection"])
    if sel.startswith("over") or sel == "o":
        return "over"
    if sel.startswith("under") or sel == "u":
        return "under"
    comp = ev["competitions"][0]
    for c in comp["competitors"]:
        if _team_hit(pick["selection"], c):
            return c["homeAway"]
    if _team_hit(pick["selection"], {"team": {"displayName": pick["home"]}}):
        return "home"
    if _team_hit(pick["selection"], {"team": {"displayName": pick["away"]}}):
        return "away"
    raise PickParseError(f"cannot tell which side {pick['selection']!r} is")


def _close_odds(ev: dict) -> dict | None:
    odds = (ev.get("competitions") or [{}])[0].get("odds") or []
    for o in odds:
        name = (o.get("provider") or {}).get("name", "").lower()
        if "draft" in name:
            return o
    return odds[0] if odds else None


def _price(v):
    try:
        v = str(v).strip().upper()
        return 100 if v in ("EVEN", "EV") else int(float(v))
    except (TypeError, ValueError):
        return None


def _line(v):
    m = _NUM.search(str(v or ""))
    return float(m.group(0)) if m else None


def attach_close(pick: dict, ev: dict) -> None:
    """Fill close_price / close_other_price / close_line from the event's
    close odds, unless a comment override already set them. Only full-game
    Spread / Total / Moneyline have ESPN closes."""
    if pick.get("close_source") == "COMMENT":
        return
    if pick["market"] not in ("Spread", "Total", "Moneyline"):
        return
    o = _close_odds(ev)
    if not o:
        return
    side = _side(pick, ev)
    other = {"home": "away", "away": "home", "over": "under", "under": "over"}[side]
    try:
        if pick["market"] == "Moneyline":
            ml = o["moneyline"]
            cp, op = _price(ml[side]["close"]["odds"]), _price(ml[other]["close"]["odds"])
            line = None
        elif pick["market"] == "Spread":
            ps = o["pointSpread"]
            cp, op = _price(ps[side]["close"]["odds"]), _price(ps[other]["close"]["odds"])
            line = _line(ps[side]["close"]["line"])
        else:
            tt = o["total"]
            cp, op = _price(tt[side]["close"]["odds"]), _price(tt[other]["close"]["odds"])
            line = _line(tt[side]["close"]["line"])
    except (KeyError, TypeError):
        return
    if cp is None:
        return
    pick.update(close_price=cp, close_other_price=op, close_line=line,
                close_source="ESPN_" + ((o.get("provider") or {}).get("name") or "ODDS").upper().replace(" ", "_"))
    # A close at a different number than the pick is not comparable price-for-price;
    # keep it only when the lines match (CLV in price), else drop it.
    if pick["market"] != "Moneyline" and line is not None and pick["line"] is not None:
        mine = abs(pick["line"]) if pick["market"] == "Total" else pick["line"]
        theirs = abs(line) if pick["market"] == "Total" else line
        if abs(mine - theirs) > 1e-9:
            pick["close_line_moved"] = round(theirs - mine, 1)
            for k in ("close_price", "close_other_price"):
                pick.pop(k, None)
            pick["close_source"] = "LINE_MOVED_NO_PRICE_CLV"


# ---------------------------------------------------------------- step 3
def _score(ev: dict, side: str) -> float | None:
    for c in ev["competitions"][0]["competitors"]:
        if c.get("homeAway") == side:
            try:
                return float(c.get("score"))
            except (TypeError, ValueError):
                return None
    return None


def is_final(ev: dict) -> bool:
    st = (ev.get("status") or (ev.get("competitions") or [{}])[0].get("status") or {}).get("type", {})
    return bool(st.get("completed")) and st.get("state") == "post"


def settle(pick: dict, ev: dict) -> None:
    if pick.get("result_source") == "COMMENT" or pick.get("void"):
        return
    if not is_final(ev) or pick["market"] not in ("Spread", "Total", "Moneyline", "Team Total"):
        return
    h, a = _score(ev, "home"), _score(ev, "away")
    if h is None or a is None:
        return
    side = _side(pick, ev)
    if pick["market"] == "Moneyline":
        mine, theirs = (h, a) if side == "home" else (a, h)
        d = mine - theirs
    elif pick["market"] == "Spread":
        mine, theirs = (h, a) if side == "home" else (a, h)
        d = mine - theirs + pick["line"]
    elif pick["market"] == "Total":
        d = (h + a - pick["line"]) * (1 if side == "over" else -1)
    else:  # Team Total: selection like "Liberty Under"
        team = "home" if _team_hit(pick["selection"].split()[0], {"team": {"displayName": pick["home"]}}) else "away"
        pts = h if team == "home" else a
        d = (pts - pick["line"]) * (-1 if "under" in pick["selection"].lower() else 1)
    pick["result"] = "win" if d > 0 else ("loss" if d < 0 else "push")
    pick["result_source"] = "ESPN_FINAL"
    pick["final"] = f"{pick['away']} {a:g} @ {pick['home']} {h:g}"


def scoreboard_dates(pick: dict, days_ahead: int = 2) -> list[str]:
    d0 = datetime.fromisoformat(pick["posted_at"]).astimezone(CT).date()
    return [(d0 + timedelta(days=i)).strftime("%Y%m%d") for i in range(days_ahead + 1)]


# ---------------------------------------------------------------- step 4
def render_table(rows: list[dict], issues_seen: int, errors: list[str], asof: str) -> str:
    out = [f"## Capper rankings — {asof}", "",
           "| # | Account | Score | Grade | Graded | CLV pts | Adj ROI | Flags |",
           "|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        clv = "—" if r["clv_pct"] is None else f"{r['clv_pct']:+.2f}"
        out.append(f"| {i} | {r['account']} | {r['score']:.0f} | {r['grade']} | {r['picks_graded']} | "
                   f"{clv} | {r['adj_roi']:+.1%} | {', '.join(r['flags']) or '—'} |")
    out += ["", f"{issues_seen} [CAPPER] issues read. CLV is fair-close minus entry implied probability "
            "(percentage points), only when the close is at the same number. Small samples are shrunk "
            "toward −4.5% ROI."]
    if errors:
        out += ["", "<details><summary>Picks not counted (" + str(len(errors)) + ")</summary>", ""]
        out += [f"- {e}" for e in errors]
        out += ["", "</details>"]
    return "\n".join(out) + "\n"
