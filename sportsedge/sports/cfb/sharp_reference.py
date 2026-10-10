"""Sharp/consensus no-vig reference for CFB card rows (OddsJam-style +EV check).

The SportsEdge CFB model is unvalidated against closing lines, so probation
(v3) needs the market itself to say the DraftKings price is good: DK must beat
a fair probability taken from OTHER books on the exact same line.

Reference rule (frozen):
  * Pinnacle two-sided no-vig on the exact same line, if present; else
  * mean two-sided no-vig of >= 2 non-DraftKings books on the exact same line.
  * Anything else -> no reference (the row cannot get probation).

Inputs are other-book quotes in the compact phone form, attached to a board row:
  {"away": "Indiana", "home": "Nebraska", "ml": [...], "spread": [...], "total": [...],
   "peers": [{"book": "fanduel", "ml": [-330, 260], "spread": [-8.5, -112, -108],
              "total": [48.5, -110, -110]}, ...]}
or as The Odds API events (converted by ``peers_from_odds_api_events``).
Never infers a missing side, never converts between different lines.
"""
from __future__ import annotations

import re
import unicodedata

SHARP_BOOKS = ("pinnacle", "circa", "bookmaker")
MIN_CONSENSUS_BOOKS = 2


def _implied(a: float) -> float:
    a = float(a)
    if -100.0 < a < 100.0:
        raise ValueError("SHARP_REF_AMERICAN_ODDS_INVALID")
    return 100.0 / (a + 100.0) if a > 0 else -a / (-a + 100.0)


def _pair(p_a: float, p_b: float):
    s = p_a + p_b
    return (p_a / s, p_b / s) if s > 0 else None


def _norm(name: str) -> str:
    t = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii").lower()
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    t = " ".join(t.split())
    aliases = {"mississippi": "ole miss", "massachusetts": "umass", "connecticut": "uconn",
               "miami oh": "miami ohio", "miami ohio": "miami ohio", "hawai i": "hawaii",
               "appalachian state": "app state", "north carolina state": "nc state"}
    return aliases.get(t, t)


def same_team(a: str, b: str) -> bool:
    """'Indiana' matches 'Indiana Hoosiers'; 'Miami (OH)' never matches 'Miami Hurricanes'."""
    x, y = _norm(a), _norm(b)
    if not x or not y:
        return False
    if x == y:
        return True
    short, long_ = (x, y) if len(x) <= len(y) else (y, x)
    if not long_.startswith(short + " "):
        return False
    rest = long_[len(short) + 1:].split()
    # Reject 'state'/'ohio'/'tech' style suffixes that name a different school.
    return bool(rest) and rest[0] not in {"state", "st", "ohio", "oh", "tech", "a", "international", "southern"}


def peer_fair_probs(peer: dict):
    """{(market, side, line): fair_p} from one book's compact quotes (two-sided only)."""
    out = {}
    if peer.get("ml"):
        a, h = peer["ml"]
        pr = _pair(_implied(a), _implied(h))
        if pr:
            out[("MONEYLINE", "AWAY", None)] = pr[0]
            out[("MONEYLINE", "HOME", None)] = pr[1]
    if peer.get("spread"):
        line, a, h = peer["spread"]
        pr = _pair(_implied(a), _implied(h))
        if pr:
            out[("SPREAD", "AWAY", float(line))] = pr[0]
            out[("SPREAD", "HOME", -float(line))] = pr[1]
    if peer.get("total"):
        line, o, u = peer["total"]
        pr = _pair(_implied(o), _implied(u))
        if pr:
            out[("TOTAL", "OVER", float(line))] = pr[0]
            out[("TOTAL", "UNDER", float(line))] = pr[1]
    return out


def reference_for(peers: list, market: str, side: str, line):
    """Return (fair_p, method, books) or None under the frozen reference rule."""
    key = (str(market).upper(), str(side).upper(), None if line in (None, "") or market == "MONEYLINE" else float(line))
    by_book = {}
    for peer in peers or []:
        book = str(peer.get("book") or "").strip().lower()
        if not book or book == "draftkings":
            continue
        try:
            probs = peer_fair_probs(peer)
        except (TypeError, ValueError):
            continue
        if key in probs:
            by_book[book] = probs[key]
    for sharp in SHARP_BOOKS:
        if sharp in by_book:
            return by_book[sharp], "SHARP_BOOK_NO_VIG:" + sharp, [sharp]
    if len(by_book) >= MIN_CONSENSUS_BOOKS:
        books = sorted(by_book)
        return sum(by_book[b] for b in books) / len(books), "CONSENSUS_NO_VIG", books
    return None


def peers_from_odds_api_events(events: list, away: str, home: str) -> list:
    """Convert The Odds API events into compact peers for one game (exact pairs only)."""
    peers = []
    for ev in events or []:
        ea, eh = ev.get("away_team") or "", ev.get("home_team") or ""
        if not (same_team(away, ea) and same_team(home, eh)):
            continue
        for bk in ev.get("bookmakers") or []:
            peer = {"book": str(bk.get("key") or "").lower()}
            for m in bk.get("markets") or []:
                outs = m.get("outcomes") or []
                if len(outs) != 2:
                    continue
                k = m.get("key")
                try:
                    if k == "h2h":
                        a = next(o for o in outs if same_team(away, o["name"]))
                        h = next(o for o in outs if same_team(home, o["name"]))
                        peer["ml"] = [a["price"], h["price"]]
                    elif k == "spreads":
                        a = next(o for o in outs if same_team(away, o["name"]))
                        h = next(o for o in outs if same_team(home, o["name"]))
                        if abs(float(a["point"]) + float(h["point"])) < 1e-9:
                            peer["spread"] = [float(a["point"]), a["price"], h["price"]]
                    elif k == "totals":
                        o = next(x for x in outs if str(x["name"]).lower() == "over")
                        u = next(x for x in outs if str(x["name"]).lower() == "under")
                        if abs(float(o["point"]) - float(u["point"])) < 1e-9:
                            peer["total"] = [float(o["point"]), o["price"], u["price"]]
                except (StopIteration, KeyError, TypeError, ValueError):
                    continue
            if len(peer) > 1:
                peers.append(peer)
    return peers


def attach_sharp_reference(results: list, board: list, events: list | None = None) -> int:
    """Set sharp_fair_p / sharp_method / sharp_books on card rows. Returns rows attached."""
    attached = 0
    for r in results or []:
        matchup = str(r.get("matchup") or "")
        if " @ " not in matchup or not r.get("market"):
            continue
        away, home = matchup.split(" @ ", 1)
        peers = []
        for b in board or []:
            if isinstance(b, dict) and same_team(away, b.get("away", "")) and same_team(home, b.get("home", "")):
                peers.extend(b.get("peers") or [])
        if events:
            peers.extend(peers_from_odds_api_events(events, away, home))
        ref = reference_for(peers, r["market"], r.get("side"), r.get("line"))
        if ref is None:
            continue
        r["sharp_fair_p"] = round(ref[0], 6)
        r["sharp_method"] = ref[1]
        r["sharp_books"] = ref[2]
        attached += 1
    return attached
