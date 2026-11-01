"""Daily +EV board: DraftKings prices vs Pinnacle no-vig fair prices, every market both books post.

One command:  python simple/board.py run OUT_DIR
  1. /v4/tournaments for American football (14) and basketball (11) -> NFL, NCAA football, NBA, NCAA basketball.
  2. /v4/participants per sport, once per day (team names), and /v4/markets once ever (cached).
  3. /v4/odds-by-tournaments once for draftkings, once for pinnacle.
  4. For every fixture/market/line/player both books post: Pinnacle fair p (multiplicative de-vig over the
     complete outcome group), EV of the DK price = p * dk_decimal - 1. Bets: EV >= MIN_EV. EV > MAX_EV is
     dropped as a likely mapping error.
Quote rules: a book that is suspended, a market with marketActive false, or an outcome with active false
is skipped. Each quote must carry a changedAt no more than MAX_QUOTE_CHANGE_AGE_S before the run; a
missing or unparseable changedAt drops the quote. The board is stamped with its capture time and is
good for BOARD_GOOD_FOR_S after it (owner 1800 s quote-age ruling, 2026-10-25).
Hard cap: MAX_CALLS_PER_DAY OddsPapi calls (owner budget 20/day, #2447 6561970754), counted in OUT_DIR/calls.json.
A calls.json that exists but cannot be read as a JSON object fails closed (no calls).
Calls are spaced PACE_S apart; a 429 is retried once (the retry is budgeted too).
NHL is paused and MLB DK auto-acquisition is off, so neither is requested.
The key comes from SPORTSEDGE_ODDSPAPI_KEY and is never printed or written.
`python simple/board.py selftest` runs offline checks with synthetic payloads.
`python simple/board.py rebuild OUT_DIR DAY HHMM` re-prices saved raw payloads with no calls.
"""
import json, os, re, sys, time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://api.oddspapi.io/v4"
SPORTS = {14: re.compile(r"^(NFL|NCAA.*)$", re.I), 11: re.compile(r"^(NBA|NCAA.*)$", re.I)}
SPORT_TAG = {14: "football", 11: "basketball"}
MIN_EV, MAX_EV = 0.03, 0.40
MAX_CALLS_PER_DAY = 20
PACE_S, RETRY_429_S, MAX_RETRY_WAIT_S = 3.0, 15.0, 60.0
MAX_QUOTE_CHANGE_AGE_S = 3 * 3600
BOARD_GOOD_FOR_S = 1800
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


_last_call = [None]


def get(endpoint, params, key, budget, opener=urlopen, sleep=time.sleep, clock=time.monotonic):
    """One OddsPapi GET. Calls are spaced PACE_S apart (the provider 429s back-to-back calls).
    A 429 is retried once after Retry-After (capped) or RETRY_429_S; every attempt is budgeted."""
    for attempt in (0, 1):
        if _last_call[0] is not None:
            wait = PACE_S - (clock() - _last_call[0])
            if wait > 0:
                sleep(wait)
        budget.spend()  # counted before the request, so a failed call still counts
        _last_call[0] = clock()
        req = Request(API + endpoint + "?" + urlencode(dict(params, apiKey=key)),
                      headers={"Accept": "application/json", "User-Agent": "SportsEdge-Board/1"})
        try:
            with opener(req, timeout=60) as r:
                blob = r.read(60_000_001)
        except HTTPError as e:
            if e.code == 429 and attempt == 0:
                try:
                    pause = min(max(float(e.headers.get("Retry-After")), 0.0), MAX_RETRY_WAIT_S)
                except (TypeError, ValueError, AttributeError):
                    pause = RETRY_429_S
                sleep(pause)
                continue
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


def parse_time(v):
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else None


def quotes(fixture, book, asof):
    """{(market_id, player, line): {side_key: (decimal, changedAt, bookmakerOutcomeId)}} for one fixture
    and book: live, active, recently-changed prices only."""
    out = {}
    b = (fixture.get("bookmakerOdds") or {}).get(book)
    if not isinstance(b, dict) or b.get("bookmakerIsActive") is False or b.get("suspended") is True:
        return out
    oldest = asof - timedelta(seconds=MAX_QUOTE_CHANGE_AGE_S)
    for mid, m in (b.get("markets") or {}).items():
        if not isinstance(m, dict) or m.get("marketActive") is False:
            continue
        for oid, o in (m.get("outcomes") or {}).items():
            if not isinstance(o, dict):
                continue
            for _, p in (o.get("players") or {}).items():
                if not isinstance(p, dict) or p.get("active") is False:
                    continue
                d = decimal_price(p.get("price"))
                ch = parse_time(p.get("changedAt"))
                if d is None or ch is None or ch < oldest or ch > asof + timedelta(minutes=5):
                    continue
                name = (p.get("playerName") or "").strip()
                boid = str(p.get("bookmakerOutcomeId") or "")
                ls = LINE_SIDE.match(boid)
                if ls and name:  # player prop line: group by player + line, side = over/under
                    key, side = (str(mid), name.lower(), ls.group(1)), ls.group(2).lower()
                else:            # game market: market id carries the line; side = outcome id
                    key, side = (str(mid), name.lower(), ""), str(oid)
                grp = out.setdefault(key, {})
                if side in grp:  # duplicate side -> ambiguous, drop whole group
                    grp["__dup__"] = None
                grp[side] = (d, ch, boid)
    return {k: v for k, v in out.items() if "__dup__" not in v}


def fair(group):
    """Multiplicative de-vig over {side: decimal}. None unless 2+ outcomes and a sane overround."""
    if len(group) < 2:
        return None
    inv = {s: 1.0 / d for s, d in group.items()}
    tot = sum(inv.values())
    if not 1.0 <= tot <= 1.15:
        return None
    return {s: v / tot for s, v in inv.items()}


def to_american(d):
    return int(round((d - 1) * 100)) if d >= 2 else int(round(-100 / (d - 1)))


def side_label(pin_boid, home, away):
    """Readable side from Pinnacle's own outcome id, e.g. 'away/79.5/under' -> 'Duke Under 79.5'."""
    parts = [x for x in pin_boid.split("/") if x]
    words = []
    for x in parts:
        lx = x.lower()
        if lx == "home":
            words.append(home)
        elif lx == "away":
            words.append(away)
        elif lx in ("over", "under", "draw"):
            words.append(lx.title())
        else:
            words.append(x)
    # put the number after Over/Under: ['20.5', 'Over'] -> ['Over', '20.5']
    if len(words) >= 2 and words[-1] in ("Over", "Under") and re.match(r"^[+-]?\d", words[-2]):
        words[-2], words[-1] = words[-1], words[-2]
    return " ".join(str(w) for w in words) or pin_boid


def board(dk_fixtures, pin_fixtures, market_names, tourn_names, asof, teams=None):
    teams = teams or {}
    pin = {f.get("fixtureId"): f for f in pin_fixtures if isinstance(f, dict)}
    rows = []
    for f in dk_fixtures:
        if not isinstance(f, dict) or f.get("fixtureId") not in pin:
            continue
        start = f.get("startTime") or ""
        st = parse_time(start)
        if st is None or st <= asof:
            continue  # started or unknown start: pregame only
        home = teams.get(str(f.get("participant1Id"))) or f.get("participant1Name") or str(f.get("participant1Id"))
        away = teams.get(str(f.get("participant2Id"))) or f.get("participant2Name") or str(f.get("participant2Id"))
        dq, pq = quotes(f, "draftkings", asof), quotes(pin[f["fixtureId"]], "pinnacle", asof)
        for key, dgrp in dq.items():
            pgrp = pq.get(key)
            if not pgrp or set(pgrp) != set(dgrp):
                continue  # need the same complete outcome set at both books
            fp = fair({s: v[0] for s, v in pgrp.items()})
            if fp is None:
                continue
            for side, (dkd, dch, _) in dgrp.items():
                ev = fp[side] * dkd - 1
                pin_boid = pgrp[side][2]
                if key[1]:
                    bet = "%s %s %s" % (key[1].title(), side.title(), key[2])
                else:
                    bet = side_label(pin_boid, home, away)
                rows.append({
                    "fixture_id": f["fixtureId"], "start": start,
                    "tournament": tourn_names.get(f.get("tournamentId"), str(f.get("tournamentId"))),
                    "game": "%s @ %s" % (away, home),
                    "market_id": key[0], "market": market_names.get(key[0], key[0]),
                    "player": key[1], "line": key[2], "side": side, "bet": bet,
                    "dk_decimal": round(dkd, 4), "dk_american": to_american(dkd),
                    "dk_changed_at": dch.isoformat(), "pinnacle_changed_at": pgrp[side][1].isoformat(),
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
    return names


def render(bets, n_rows, asof, notes):
    good = asof + timedelta(seconds=BOARD_GOOD_FOR_S)
    lines = ["# SportsEdge picks %s" % asof.strftime("%Y-%m-%d %H:%M UTC"), "",
             "DraftKings price vs Pinnacle no-vig fair price. Bets = EV ≥ +%d%%. %d priced lines compared. "
             "Prices captured %s; recheck the DK price after %s UTC." %
             (MIN_EV * 100, n_rows, asof.strftime("%H:%M"), good.strftime("%H:%M")), ""]
    if not bets:
        lines.append("No DraftKings price beats Pinnacle fair by +%d%% right now." % (MIN_EV * 100))
    else:
        lines += ["| # | Game | League | Market | Bet | DK | Fair % | EV |", "|---|---|---|---|---|---|---|---|"]
        for i, r in enumerate(bets[:60], 1):
            lines.append("| %d | %s | %s | %s | %s | %+d | %.1f | %+.1f%% |" % (
                i, r["game"], r["tournament"], r["market"], r["bet"], r["dk_american"],
                100 * r["pinnacle_fair_p"], 100 * r["ev"]))
    if notes:
        lines += ["", "Notes: " + "; ".join(notes)]
    return "\n".join(lines) + "\n"


def load_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# ---------- run ----------
def write_board(out_dir, raw_dir, books, names, tnames, teams, asof, notes):
    rows, bets = board(books["draftkings"], books["pinnacle"], names, tnames, asof, teams)
    notes.append("fixtures DK %d / Pinnacle %d" % (len(books["draftkings"]), len(books["pinnacle"])))
    stamp = asof.strftime("%H%M")
    with open(os.path.join(raw_dir, "board_%s.json" % stamp), "w") as fh:
        json.dump({"asof": asof.isoformat(), "bets": bets, "n_compared": len(rows), "notes": notes}, fh, indent=1)
    md = render(bets, len(rows), asof, notes)
    for p in (os.path.join(raw_dir, "board_%s.md" % stamp), os.path.join(out_dir, "LATEST.md")):
        with open(p, "w") as fh:
            fh.write(md)
    return md


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
                tids.append(t["tournamentId"])
                tnames[t["tournamentId"]] = name if name in ("NFL", "NBA") else "%s %s" % (name, SPORT_TAG[sid])
    if not tids:
        raise Refused("NO_TOURNAMENTS_MATCHED")
    teams = {}
    for sid in SPORTS:  # team names: one call per sport per day, cached; a failure only costs labels
        tpath = os.path.join(raw_dir, "participants_%d.json" % sid)
        traw = load_json(tpath)
        if not isinstance(traw, dict):
            try:
                traw = get("/participants", {"sportId": sid}, key, budget, opener)
                json.dump(traw, open(tpath, "w"))
            except Refused as e:
                notes.append("team names unavailable for sport %d (%s)" % (sid, e))
                traw = {}
        if isinstance(traw, dict):
            teams.update({str(k): str(v) for k, v in traw.items() if isinstance(v, (str, int))})
    mpath = os.path.join(out_dir, "markets.json")
    mraw = load_json(mpath)
    if mraw is None:
        mraw = get("/markets", {}, key, budget, opener)
        json.dump(mraw, open(mpath, "w"))
    names = markets_index(mraw)
    books = {}
    for book in ("draftkings", "pinnacle"):
        books[book] = as_list(get("/odds-by-tournaments", {
            "bookmaker": book, "tournamentIds": ",".join(map(str, tids)), "oddsFormat": "decimal"},
            key, budget, opener))
        json.dump(books[book], open(os.path.join(raw_dir, "%s_%s.json" % (book, asof.strftime("%H%M"))), "w"))
    notes.append("tournaments: " + ", ".join(sorted(set(tnames.values()))))
    notes.append("OddsPapi calls today %d/%d" % (budget.used(), budget.cap))
    return write_board(out_dir, raw_dir, books, names, tnames, teams, asof, notes)


def rebuild(out_dir, day, stamp):
    """Re-price saved raw payloads (no API calls). asof = the capture time in the file names."""
    raw_dir = os.path.join(out_dir, day)
    asof = datetime.strptime(day + stamp, "%Y-%m-%d%H%M").replace(tzinfo=timezone.utc)
    books = {b: as_list(load_json(os.path.join(raw_dir, "%s_%s.json" % (b, stamp)))) for b in ("draftkings", "pinnacle")}
    teams, tnames = {}, {}
    for sid, pat in SPORTS.items():
        p = load_json(os.path.join(raw_dir, "participants_%d.json" % sid))
        if isinstance(p, dict):
            teams.update({str(k): str(v) for k, v in p.items()})
        for t in as_list(load_json(os.path.join(raw_dir, "tournaments_%d.json" % sid))):
            if isinstance(t, dict) and pat.match(str(t.get("tournamentName") or "")):
                name = str(t["tournamentName"])
                tnames[t["tournamentId"]] = name if name in ("NFL", "NBA") else "%s %s" % (name, SPORT_TAG[sid])
    names = markets_index(load_json(os.path.join(out_dir, "markets.json")) or [])
    return write_board(out_dir, raw_dir, books, names, tnames, teams, asof, ["rebuilt from saved payloads, 0 calls"])


# ---------- offline self-test ----------
def selftest():
    asof = datetime(2026, 11, 1, tzinfo=timezone.utc)
    fresh = (asof - timedelta(minutes=10)).isoformat()

    def player(price, name="", boid="", active=True, changed=fresh):
        return {"price": price, "playerName": name, "bookmakerOutcomeId": boid, "active": active, "changedAt": changed}

    def fx(book, ml, props, start="2099-01-01T18:00:00Z", ml_boids=("", "")):
        return {"fixtureId": "f1", "tournamentId": 1, "startTime": start,
                "participant1Id": 10, "participant2Id": 20,
                "bookmakerOdds": {book: {"bookmakerIsActive": True, "suspended": False, "markets": {
                    "131": {"marketActive": True, "outcomes": {"131": {"players": {"0": player(ml[0], boid=ml_boids[0])}},
                                                              "132": {"players": {"0": player(ml[1], boid=ml_boids[1])}}}},
                    "900": {"outcomes": {"1": {"players": {"0": player(props[0], "A Smith", "55.5/over")}},
                                         "2": {"players": {"0": player(props[1], "A Smith", "55.5/under")}}}}}}}}
    teams = {"10": "Home Team", "20": "Away Team"}
    pin = fx("pinnacle", (1.80, 2.10), (1.90, 1.90), ml_boids=("home", "away"))
    dk = fx("draftkings", (1.95, 1.87), (2.10, 1.74))
    rows, bets = board([dk], [pin], {"131": "Moneyline"}, {1: "NFL"}, asof, teams)
    assert len(rows) == 4, rows
    by = {(r["market_id"], r["side"]): r for r in rows}
    pf = (1 / 1.8) / (1 / 1.8 + 1 / 2.1)
    assert abs(by[("131", "131")]["ev"] - round(pf * 1.95 - 1, 4)) < 1e-4
    assert abs(by[("900", "over")]["ev"] - 0.05) < 1e-4          # 0.5 * 2.10 - 1
    assert [(b["market_id"], b["side"]) for b in bets] == [("131", "131"), ("900", "over")], bets
    assert by[("131", "131")]["bet"] == "Home Team" and by[("131", "131")]["game"] == "Away Team @ Home Team"
    assert by[("900", "over")]["bet"] == "A Smith Over 55.5"
    assert side_label("away/79.5/under", "H", "A") == "A Under 79.5"
    assert side_label("20.5/over", "H", "A") == "Over 20.5"
    assert side_label("3.0/home", "H", "A") == "3.0 H"
    # started games are excluded
    assert board([fx("draftkings", (1.95, 1.87), (2.1, 1.74), start="2020-01-01T00:00:00Z")], [pin], {}, {}, asof)[0] == []
    # inactive / missing side -> group incomplete -> no row
    dk2 = fx("draftkings", (1.95, 1.87), (2.10, 1.74))
    dk2["bookmakerOdds"]["draftkings"]["markets"]["131"]["outcomes"]["132"]["players"]["0"]["active"] = False
    assert all(r["market_id"] != "131" for r in board([dk2], [pin], {}, {}, asof)[0])
    # marketActive false -> no row for that market
    dk4 = fx("draftkings", (1.95, 1.87), (2.10, 1.74))
    dk4["bookmakerOdds"]["draftkings"]["markets"]["131"]["marketActive"] = False
    assert all(r["market_id"] != "131" for r in board([dk4], [pin], {}, {}, asof)[0])
    # suspended book -> no rows
    dk5 = fx("draftkings", (1.95, 1.87), (2.10, 1.74))
    dk5["bookmakerOdds"]["draftkings"]["suspended"] = True
    assert board([dk5], [pin], {}, {}, asof)[0] == []
    # stale or missing changedAt -> quote dropped
    for bad in ((asof - timedelta(seconds=MAX_QUOTE_CHANGE_AGE_S + 60)).isoformat(), None, "nope", "2026-11-01T00:00:00"):
        dk6 = fx("draftkings", (1.95, 1.87), (2.10, 1.74))
        dk6["bookmakerOdds"]["draftkings"]["markets"]["131"]["outcomes"]["131"]["players"]["0"]["changedAt"] = bad
        assert all(r["market_id"] != "131" for r in board([dk6], [pin], {}, {}, asof)[0]), bad
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

    # pacing + single 429 retry, all attempts budgeted (fake clock, no network)
    import io

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener_seq(codes):
        it = iter(codes)

        def op(req, timeout=60):
            c = next(it)
            if c != 200:
                raise HTTPError(req.full_url, c, "x", {"Retry-After": "7"} if c == 429 else {}, None)
            return Resp(b'[{"ok": 1}]')
        return op

    t, slept = [0.0], []

    def fake_sleep(s):
        slept.append(s); t[0] += s

    clock = lambda: t[0]
    _last_call[0] = None
    pb = Budget(os.path.join(d, "pace.json"), "2026-11-01", cap=10)
    assert get("/x", {}, "k", pb, opener_seq([200]), fake_sleep, clock) == [{"ok": 1}] and slept == []
    assert get("/x", {}, "k", pb, opener_seq([200]), fake_sleep, clock) == [{"ok": 1}] and slept == [PACE_S]
    assert pb.used() == 2
    slept.clear()
    assert get("/x", {}, "k", pb, opener_seq([429, 200]), fake_sleep, clock) == [{"ok": 1}]
    assert 7.0 in slept and pb.used() == 4, (slept, pb.used())
    try:
        get("/x", {}, "k", pb, opener_seq([429, 429]), fake_sleep, clock); raise AssertionError("429 twice not refused")
    except Refused as e:
        assert str(e) == "HTTP_429_/x" and pb.used() == 6, (e, pb.used())
    _last_call[0] = None
    print("selftest ok")


if __name__ == "__main__":
    if sys.argv[1:2] == ["selftest"]:
        selftest()
    elif sys.argv[1:2] == ["rebuild"]:
        print(rebuild(sys.argv[2], sys.argv[3], sys.argv[4]))
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
