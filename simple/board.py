"""Daily +EV board: DraftKings prices vs Pinnacle no-vig fair prices, every market both books post.

One command:  python simple/board.py run OUT_DIR
  1. /v4/tournaments for American football (14) and basketball (11) -> NFL, NCAA football, NBA, NCAA basketball.
  2. /v4/markets once (names for the board).
  3. /v4/odds-by-tournaments once for draftkings, once for pinnacle.
  4. For every fixture/market/line/player both books post: Pinnacle fair p (multiplicative de-vig over the
     complete outcome group), EV of the DK price = p * dk_decimal - 1. Bets: EV >= MIN_EV. EV > MAX_EV is
     dropped as a likely mapping error.
Hard cap: MAX_CALLS_PER_DAY OddsPapi calls (owner budget 20/day, #2447 6561970754), counted in OUT_DIR/calls.json.
A calls.json that exists but cannot be read as a JSON object fails closed (no calls).
NHL is paused and MLB DK auto-acquisition is off, so neither is requested.
The key comes from SPORTSEDGE_ODDSPAPI_KEY and is never printed or written.
`python simple/board.py selftest` runs offline checks with synthetic payloads.
"""
import json, os, re, sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://api.oddspapi.io/v4"
SPORTS = {14: re.compile(r"^(NFL|NCAA.*)$", re.I), 11: re.compile(r"^(NBA|NCAA.*)$", re.I)}
MIN_EV, MAX_EV = 0.03, 0.40
MAX_CALLS_PER_DAY = 20
LINE_SIDE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*/\s*([A-Za-z]+)\s*$")


class Refused(Exception):
    pass


# ---------- budget ----------
class Budget:
    """Daily call counter in a JSON file. A missing file is a fresh start. A file that exists
    but is unreadable, not JSON, or not an object fails CLOSED: no calls until it is fixed."""

    def __init__(self, path, day, cap=MAX_CALLS_PER_DAY):
        self.path, self.day, self.cap = path, day, cap
        self.corrupt, self.log = False, {}
        if os.path.lexists(path):
            try:
                with open(path) as fh:
                    self.log = json.load(fh)
            except (OSError, ValueError):
                self.corrupt = True
            if not isinstance(self.log, dict):
                self.log, self.corrupt = {}, True

    def used(self):
        if self.corrupt:
            return self.cap
        v = self.log.get(self.day, 0)
        return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else self.cap

    def spend(self):
        if self.corrupt:
            raise Refused("BUDGET_FILE_CORRUPT")
        if self.used() >= self.cap:
            raise Refused("DAILY_CALL_CAP_REACHED")
        self.log[self.day] = self.used() + 1
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(self.log, fh, indent=1, sort_keys=True)
        os.replace(tmp, self.path)


def get(endpoint, params, key, budget, opener=urlopen):
    budget.spend()  # counted before the request, so a failed call still counts
    req = Request(API + endpoint + "?" + urlencode(dict(params, apiKey=key)),
                  headers={"Accept": "application/json", "User-Agent": "SportsEdge-Board/1"})
    try:
        with opener(req, timeout=60) as r:
            blob = r.read(60_000_001)
    except HTTPError as e:
        raise Refused("HTTP_%d_%s" % (e.code, endpoint)) from None
    except (URLError, OSError):
        raise Refused("UNAVAILABLE_" + endpoint) from None
    if len(blob) > 60_000_000:
        raise Refused("TOO_LARGE_" + endpoint)
    try:
        return json.loads(blob)
    except ValueError:
        raise Refused("BAD_JSON_" + endpoint) from None


# ---------- parsing ----------
def as_list(x):
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        for k in ("data", "fixtures", "tournaments", "markets", "result"):
            if isinstance(x.get(k), list):
                return x[k]
    return []


def decimal_price(v):
    if isinstance(v, bool):
        return None
    try:
        d = float(v)
    except (TypeError, ValueError):
        return None
    return d if 1.0 < d < 1001 else None


def quotes(fixture, book):
    """{(market_id, player, line): {side_key: decimal}} for one fixture and book, active prices only."""
    out = {}
    b = (fixture.get("bookmakerOdds") or {}).get(book)
    if not isinstance(b, dict) or b.get("bookmakerIsActive") is False:
        return out
    for mid, m in (b.get("markets") or {}).items():
        if not isinstance(m, dict):
            continue
        for oid, o in (m.get("outcomes") or {}).items():
            if not isinstance(o, dict):
                continue
            for _, p in (o.get("players") or {}).items():
                if not isinstance(p, dict) or p.get("active") is False:
                    continue
                d = decimal_price(p.get("price"))
                if d is None:
                    continue
                name = (p.get("playerName") or "").strip()
                ls = LINE_SIDE.match(str(p.get("bookmakerOutcomeId") or ""))
                if ls and name:  # player prop line: group by player + line, side = over/under
                    key, side = (str(mid), name.lower(), ls.group(1)), ls.group(2).lower()
                else:            # game market: market id carries the line; side = outcome id
                    key, side = (str(mid), name.lower(), ""), str(oid)
                grp = out.setdefault(key, {})
                if side in grp:  # duplicate side -> ambiguous, drop whole group
                    grp["__dup__"] = 1.0
                grp[side] = d
    return {k: v for k, v in out.items() if "__dup__" not in v}


def fair(group):
    """Multiplicative de-vig. None unless 2+ outcomes and a sane overround."""
    if len(group) < 2:
        return None
    inv = {s: 1.0 / d for s, d in group.items()}
    tot = sum(inv.values())
    if not 1.0 <= tot <= 1.15:
        return None
    return {s: v / tot for s, v in inv.items()}


def to_american(d):
    return int(round((d - 1) * 100)) if d >= 2 else int(round(-100 / (d - 1)))


def board(dk_fixtures, pin_fixtures, market_names, tourn_names, asof):
    pin = {f.get("fixtureId"): f for f in pin_fixtures if isinstance(f, dict)}
    rows = []
    for f in dk_fixtures:
        if not isinstance(f, dict) or f.get("fixtureId") not in pin:
            continue
        start = f.get("startTime") or ""
        try:
            if datetime.fromisoformat(str(start).replace("Z", "+00:00")) <= asof:
                continue  # started: pregame only
        except ValueError:
            continue
        dq, pq = quotes(f, "draftkings"), quotes(pin[f["fixtureId"]], "pinnacle")
        for key, dgrp in dq.items():
            pgrp = pq.get(key)
            if not pgrp or set(pgrp) != set(dgrp):
                continue  # need the same complete outcome set at both books
            fp = fair(pgrp)
            if fp is None:
                continue
            for side, dkd in dgrp.items():
                ev = fp[side] * dkd - 1
                rows.append({
                    "fixture_id": f["fixtureId"], "start": start,
                    "tournament": tourn_names.get(f.get("tournamentId"), str(f.get("tournamentId"))),
                    "game": "%s @ %s" % (f.get("participant2Name") or f.get("participant2Id"),
                                         f.get("participant1Name") or f.get("participant1Id")),
                    "market_id": key[0], "market": market_names.get(key[0], key[0]),
                    "player": key[1], "line": key[2], "side": side,
                    "dk_decimal": round(dkd, 4), "dk_american": to_american(dkd),
                    "pinnacle_fair_p": round(fp[side], 4), "ev": round(ev, 4)})
    bets = sorted((r for r in rows if MIN_EV <= r["ev"] <= MAX_EV), key=lambda r: -r["ev"])
    return rows, bets


def markets_index(raw):
    names = {}
    for m in as_list(raw):
        if isinstance(m, dict) and m.get("marketId") is not None:
            label = m.get("marketName") or m.get("name") or str(m["marketId"])
            hcap = m.get("handicap")
            if hcap not in (None, "", 0):
                label = "%s %s" % (label, hcap)
            names[str(m["marketId"])] = label
            for o in m.get("outcomes") or []:
                if isinstance(o, dict) and o.get("outcomeId") is not None:
                    names["%s:%s" % (m["marketId"], o["outcomeId"])] = o.get("outcomeName") or o.get("name") or ""
    return names


def render(bets, n_rows, asof, notes):
    lines = ["# SportsEdge picks %s" % asof.strftime("%Y-%m-%d %H:%M UTC"), "",
             "DraftKings price vs Pinnacle no-vig fair price. Bets = EV ≥ +%d%%. %d priced lines compared." %
             (MIN_EV * 100, n_rows), ""]
    if not bets:
        lines.append("No DraftKings price beats Pinnacle fair by +%d%% right now." % (MIN_EV * 100))
    else:
        lines += ["| # | Game | Market | Bet | DK | Fair % | EV |", "|---|---|---|---|---|---|---|"]
        for i, r in enumerate(bets[:60], 1):
            side = r["side"]
            bet = " ".join(x for x in (r["player"].title(), side.upper() if r["line"] else side, r["line"]) if x)
            lines.append("| %d | %s (%s) | %s | %s | %+d | %.1f | %+.1f%% |" % (
                i, r["game"], r["tournament"], r["market"], bet, r["dk_american"],
                100 * r["pinnacle_fair_p"], 100 * r["ev"]))
    if notes:
        lines += ["", "Notes: " + "; ".join(notes)]
    return "\n".join(lines) + "\n"


# ---------- run ----------
def run(out_dir, key, opener=urlopen, now=None):
    asof = now or datetime.now(timezone.utc)
    day = asof.strftime("%Y-%m-%d")
    budget = Budget(os.path.join(out_dir, "calls.json"), day)
    raw_dir = os.path.join(out_dir, day)
    os.makedirs(raw_dir, exist_ok=True)
    notes = []
    tids, tnames = [], {}
    for sid, pat in SPORTS.items():
        traw = get("/tournaments", {"sportId": sid}, key, budget, opener)
        json.dump(traw, open(os.path.join(raw_dir, "tournaments_%d.json" % sid), "w"))
        for t in as_list(traw):
            if not isinstance(t, dict):
                continue
            name = str(t.get("tournamentName") or "")
            if pat.match(name) and (t.get("upcomingFixtures") or 0) + (t.get("futureFixtures") or 0) > 0:
                tids.append(t["tournamentId"]); tnames[t["tournamentId"]] = name
    if not tids:
        raise Refused("NO_TOURNAMENTS_MATCHED")
    mpath = os.path.join(out_dir, "markets.json")
    if os.path.exists(mpath):
        mraw = json.load(open(mpath))
    else:
        mraw = get("/markets", {}, key, budget, opener)
        json.dump(mraw, open(mpath, "w"))
    names = markets_index(mraw)
    books = {}
    for book in ("draftkings", "pinnacle"):
        books[book] = as_list(get("/odds-by-tournaments", {
            "bookmaker": book, "tournamentIds": ",".join(map(str, tids)), "oddsFormat": "decimal"},
            key, budget, opener))
        json.dump(books[book], open(os.path.join(raw_dir, "%s_%s.json" % (book, asof.strftime("%H%M"))), "w"))
    rows, bets = board(books["draftkings"], books["pinnacle"], names, tnames, asof)
    notes.append("tournaments: " + ", ".join(sorted(set(tnames.values()))))
    notes.append("fixtures DK %d / Pinnacle %d" % (len(books["draftkings"]), len(books["pinnacle"])))
    notes.append("OddsPapi calls today %d/%d" % (budget.used(), budget.cap))
    stamp = asof.strftime("%H%M")
    json.dump({"asof": asof.isoformat(), "bets": bets, "n_compared": len(rows), "notes": notes},
              open(os.path.join(raw_dir, "board_%s.json" % stamp), "w"), indent=1)
    md = render(bets, len(rows), asof, notes)
    open(os.path.join(raw_dir, "board_%s.md" % stamp), "w").write(md)
    open(os.path.join(out_dir, "LATEST.md"), "w").write(md)
    return md


# ---------- offline self-test ----------
def selftest():
    def player(price, name="", boid="", active=True):
        return {"price": price, "playerName": name, "bookmakerOutcomeId": boid, "active": active}

    def fx(book, ml, props, start="2099-01-01T18:00:00Z"):
        return {"fixtureId": "f1", "tournamentId": 1, "startTime": start,
                "participant1Name": "Home", "participant2Name": "Away",
                "bookmakerOdds": {book: {"bookmakerIsActive": True, "markets": {
                    "131": {"outcomes": {"131": {"players": {"0": player(ml[0])}},
                                         "132": {"players": {"0": player(ml[1])}}}},
                    "900": {"outcomes": {"1": {"players": {"0": player(props[0], "A Smith", "55.5/over")}},
                                         "2": {"players": {"0": player(props[1], "A Smith", "55.5/under")}}}}}}}}
    asof = datetime(2026, 11, 1, tzinfo=timezone.utc)
    pin = fx("pinnacle", (1.80, 2.10), (1.90, 1.90))
    dk = fx("draftkings", (1.95, 1.87), (2.10, 1.74))
    rows, bets = board([dk], [pin], {"131": "Moneyline"}, {1: "NFL"}, asof)
    assert len(rows) == 4, rows
    by = {(r["market_id"], r["side"]): r for r in rows}
    pf = (1 / 1.8) / (1 / 1.8 + 1 / 2.1)
    assert abs(by[("131", "131")]["ev"] - round(pf * 1.95 - 1, 4)) < 1e-4
    assert abs(by[("900", "over")]["ev"] - 0.05) < 1e-4          # 0.5 * 2.10 - 1
    assert [(b["market_id"], b["side"]) for b in bets] == [("131", "131"), ("900", "over")], bets
    # started games are excluded
    assert board([fx("draftkings", (1.95, 1.87), (2.1, 1.74), start="2020-01-01T00:00:00Z")], [pin], {}, {}, asof)[0] == []
    # inactive / missing side -> group incomplete -> no row
    dk2 = fx("draftkings", (1.95, 1.87), (2.10, 1.74))
    dk2["bookmakerOdds"]["draftkings"]["markets"]["131"]["outcomes"]["132"]["players"]["0"]["active"] = False
    assert all(r["market_id"] != "131" for r in board([dk2], [pin], {}, {}, asof)[0])
    # absurd EV quarantined from bets
    pin3 = fx("pinnacle", (1.10, 8.0), (1.9, 1.9))
    dk3 = fx("draftkings", (1.95, 1.87), (1.9, 1.9))
    assert all(b["ev"] <= MAX_EV for b in board([dk3], [pin3], {}, {}, asof)[1])
    # bad prices ignored
    assert decimal_price(True) is None and decimal_price("x") is None and decimal_price(1.0) is None
    # budget cap
    import tempfile
    d = tempfile.mkdtemp()
    b = Budget(os.path.join(d, "c.json"), "2026-11-01", cap=2)
    b.spend(); b.spend()
    try:
        b.spend(); raise AssertionError("cap not enforced")
    except Refused:
        pass
    assert Budget(os.path.join(d, "c.json"), "2026-11-01", cap=2).used() == 2
    # corrupt / non-object budget file fails closed and is left untouched (review 5729925753)
    for bad in ("{broken", "[1, 2]", "null", '"x"'):
        p = os.path.join(d, "bad.json")
        with open(p, "w") as fh:
            fh.write(bad)
        bb = Budget(p, "2026-11-01", cap=2)
        assert bb.used() == 2, bad
        try:
            bb.spend(); raise AssertionError("corrupt budget not refused: " + bad)
        except Refused as e:
            assert str(e) == "BUDGET_FILE_CORRUPT", e
        with open(p) as fh:
            assert fh.read() == bad
    # bad count for today fails closed
    for badv in (True, -1, 1.5, "3"):
        p = os.path.join(d, "v.json")
        with open(p, "w") as fh:
            json.dump({"2026-11-01": badv}, fh)
        assert Budget(p, "2026-11-01", cap=2).used() == 2, badv
    # unreadable path (a directory) fails closed
    os.mkdir(os.path.join(d, "dir.json"))
    assert Budget(os.path.join(d, "dir.json"), "2026-11-01", cap=2).corrupt
    print("selftest ok")


if __name__ == "__main__":
    if sys.argv[1:2] == ["selftest"]:
        selftest()
    elif sys.argv[1:2] == ["run"]:
        key = os.environ.get("SPORTSEDGE_ODDSPAPI_KEY")
        if not key:
            print("REFUSED: SPORTSEDGE_ODDSPAPI_KEY missing"); sys.exit(2)
        try:
            print(run(sys.argv[2], key))
        except Refused as e:
            print("REFUSED: %s" % e); sys.exit(2)
    else:
        print(__doc__)
