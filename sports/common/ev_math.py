"""EV tracker math (EV_TRACKER_POLICY_V2).

Fair prices are MARKET_FAIR_P from sharp books. Never Model_P, never a
Truth Gate input. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from statistics import NormalDist
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")
SCHEMA_VERSION = 2
_N = NormalDist()


class EVError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


# ---------- policy ----------

def load_active_policy(root) -> dict:
    root = Path(root)
    manifest = json.loads((root / "config/ev_tracker_policy_manifest.json").read_text())
    active = manifest["active"]
    raw = (root / active["path"]).read_bytes()
    policy = json.loads(raw)
    if policy.get("policy_id") != active["policy_id"]:
        raise EVError("ACTIVE_POLICY_MISMATCH", f"{active['path']} is {policy.get('policy_id')}")
    if active["policy_id"] in {s["policy_id"] for s in manifest.get("superseded", [])}:
        raise EVError("ACTIVE_POLICY_ALSO_SUPERSEDED", active["policy_id"])
    policy["_sha256"] = hashlib.sha256(raw).hexdigest()
    return policy


# ---------- records ----------

def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def seal(record: dict) -> dict:
    body = {k: v for k, v in record.items() if k != "content_sha256"}
    body["schema_version"] = SCHEMA_VERSION
    return dict(body, content_sha256=hashlib.sha256(canonical_json(body).encode()).hexdigest())


def verify_seal(record: dict) -> bool:
    body = {k: v for k, v in record.items() if k != "content_sha256"}
    return record.get("content_sha256") == hashlib.sha256(canonical_json(body).encode()).hexdigest()


def parse_utc(value) -> datetime:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise EVError("TIMESTAMP_TIMEZONE_MISSING", str(value))
    return dt


# ---------- odds ----------

def american_to_decimal(a) -> float:
    a = float(a)
    if -100 < a < 100:
        raise EVError("PRICE_INVALID", str(a))
    return 1 + a / 100 if a > 0 else 1 + 100 / abs(a)


def decimal_to_american(d: float) -> int:
    if d <= 1:
        raise EVError("PRICE_INVALID", str(d))
    return round((d - 1) * 100) if d >= 2 else round(-100 / (d - 1))


# ---------- devig ----------

def devig_multiplicative(implied):
    s = sum(implied)
    return [x / s for x in implied]


def devig_power(implied):
    if any(not 0 < x < 1 for x in implied):
        raise EVError("DEVIG_INPUT_INVALID")
    f = lambda k: sum(x ** k for x in implied) - 1
    lo, hi = 1e-3, 1e3
    if f(lo) < 0 or f(hi) > 0:
        raise EVError("DEVIG_FAILED")
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) > 0 else (lo, mid)
    p = [x ** ((lo + hi) / 2) for x in implied]
    s = sum(p)
    return [x / s for x in p]


def devig_shin(implied):
    s = sum(implied)
    if s <= 1:
        return devig_multiplicative(implied)

    def probs(z):
        return [(math.sqrt(z * z + 4 * (1 - z) * x * x / s) - z) / (2 * (1 - z)) for x in implied]

    lo, hi = 0.0, 0.99
    if sum(probs(hi)) - 1 > 0:
        raise EVError("DEVIG_FAILED")
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if sum(probs(mid)) - 1 > 0 else (lo, mid)
    p = probs((lo + hi) / 2)
    t = sum(p)
    return [x / t for x in p]


def devig(decimals, trigger_american=400, max_spread_pp=1.0):
    implied = [1 / d for d in decimals]
    power = devig_power(implied)
    if max(decimals) > american_to_decimal(trigger_american):
        others = [devig_multiplicative(implied), devig_shin(implied)]
        for i in range(len(implied)):
            vals = [power[i]] + [m[i] for m in others]
            if (max(vals) - min(vals)) * 100 > max_spread_pp:
                raise EVError("DEVIG_METHOD_SENSITIVITY")
    return power


# ---------- event identity ----------

def _norm(text: str) -> str:
    return " ".join(str(text).lower().split())


def team_matches(user_text: str, full_name: str) -> bool:
    """Exact full name, or the user's words equal the final words of the name
    ("Chiefs", "City Chiefs"). No substring guessing."""
    a, b = _norm(user_text), _norm(full_name)
    if not a:
        return False
    return a == b or b.endswith(" " + a)


def match_event(events: list, away: str, home: str, now: datetime, game_date_ct: str = None) -> dict:
    """Unique upcoming event or an error. Never picks one of several."""
    def candidates(a, h):
        out = []
        for ev in events:
            start = parse_utc(ev["commence_time"])
            if start <= now:
                continue
            if game_date_ct and start.astimezone(CT).date().isoformat() != game_date_ct:
                continue
            if team_matches(a, ev["away_team"]) and team_matches(h, ev["home_team"]):
                out.append(ev)
        return out

    straight, swapped = candidates(away, home), candidates(home, away)
    found = [(e, False) for e in straight] + [(e, True) for e in swapped if e not in straight]
    if not found:
        raise EVError("EVENT_NOT_FOUND", f"{away} at {home}")
    if len(found) > 1:
        listed = "; ".join(
            f"{e['away_team']} at {e['home_team']} {parse_utc(e['commence_time']).astimezone(CT):%b %-d %-I:%M %p} CT"
            for e, _ in found)
        raise EVError("EVENT_AMBIGUOUS", listed)
    event, was_swapped = found[0]
    return {"event": event, "swapped": was_swapped}


# ---------- close pricing ----------

def _book_line_price(outcomes, play):
    """Pick side and its paired opposite at the book's own line.
    Returns (pick_decimal, other_decimal, book_line) or None."""
    market, pick = play["market"], play["pick"]
    if market == "h2h":
        if len(outcomes) != 2:
            return None
        mine = [o for o in outcomes if o["name"] == pick]
        other = [o for o in outcomes if o["name"] != pick]
        if len(mine) != 1 or len(other) != 1:
            return None
        return float(mine[0]["price"]), float(other[0]["price"]), None
    if market == "spreads":
        other_name = play["home_team"] if pick == play["away_team"] else play["away_team"]
        mine = [o for o in outcomes if o["name"] == pick and o.get("point") is not None]
        if len(mine) != 1:
            return None
        line = float(mine[0]["point"])
        other = [o for o in outcomes if o["name"] == other_name and o.get("point") is not None
                 and float(o["point"]) == -line]
    elif market == "totals":
        opposite = "Under" if pick == "Over" else "Over"
        mine = [o for o in outcomes if o["name"] == pick and o.get("point") is not None]
        if len(mine) != 1:
            return None
        line = float(mine[0]["point"])
        other = [o for o in outcomes if o["name"] == opposite and o.get("point") is not None
                 and float(o["point"]) == line]
    else:
        raise EVError("MARKET_UNSUPPORTED", market)
    if len(other) != 1:
        return None
    return float(mine[0]["price"]), float(other[0]["price"]), line


def line_clv_pts(market: str, pick: str, taken_line: float, close_line: float) -> float:
    if market == "spreads":
        return taken_line - close_line
    if market == "totals":
        return (close_line - taken_line) if pick == "Over" else (taken_line - close_line)
    return 0.0


def prob_at_taken_line(market, pick, fair_p, book_line, taken_line, sigma):
    """NORMAL_APPROX_V1: shift a fair probability from the book's line to the taken line."""
    if book_line == taken_line or market == "h2h":
        return fair_p
    if sigma is None:
        return None
    z = _N.inv_cdf(fair_p)
    if market == "spreads":
        mu = sigma * z - book_line
        return _N.cdf((mu + taken_line) / sigma)
    if pick == "Over":
        mu = book_line + sigma * z
        return _N.cdf((mu - taken_line) / sigma)
    mu = book_line - sigma * z
    return _N.cdf((taken_line - mu) / sigma)


def grade_attempt(event_odds: dict, play: dict, policy: dict, fetched_at: datetime) -> dict:
    weights = policy["sharp_weights"]
    dv, conv = policy["devig"], policy["line_conversion"]
    sigma = conv["sigma"].get(play["sport_key"], {}).get(play["market"])
    books = {}
    for bk in event_odds.get("bookmakers", []):
        key = bk.get("key")
        if key not in weights or key == play["book"]:
            continue
        for mk in bk.get("markets", []):
            if mk.get("key") != play["market"]:
                continue
            stamp = mk.get("last_update") or bk.get("last_update")
            age = None if not stamp else (fetched_at - parse_utc(stamp)).total_seconds()
            if age is None or age > policy["max_quote_age_s"]:
                books[key] = {"status": "STALE", "age_s": age}
                continue
            found = _book_line_price(mk.get("outcomes", []), play)
            if found is None:
                books[key] = {"status": "PICK_NOT_LISTED", "age_s": age}
                continue
            pick_dec, other_dec, book_line = found
            try:
                fair = devig([pick_dec, other_dec], dv["sensitivity_trigger_american"], dv["max_method_spread_pp"])[0]
            except EVError as exc:
                return {"status": "UNAVAILABLE", "reason": exc.code, "books": books}
            entry = {"status": "PRICED", "age_s": round(age, 1), "line": book_line,
                     "pick_decimal": pick_dec, "other_decimal": other_dec, "fair_p_at_book_line": round(fair, 6)}
            if play["market"] != "h2h":
                moved = abs(book_line - float(play["line"]))
                entry["line_clv_pts"] = line_clv_pts(play["market"], play["pick"], float(play["line"]), book_line)
                usable_sigma = sigma if moved <= conv["max_line_move_pts"] else None
                p = prob_at_taken_line(play["market"], play["pick"], fair, book_line, float(play["line"]), usable_sigma)
            else:
                p = fair
            if p is not None:
                entry["prob_at_taken_line"] = round(p, 6)
                entry["prob_method"] = "SAME_LINE" if play["market"] == "h2h" or book_line == float(play["line"]) else conv["method"]
            books[key] = entry

    priced = {k: b for k, b in books.items() if b["status"] == "PRICED"}
    if not priced:
        return {"status": "UNAVAILABLE", "reason": "NO_FRESH_SHARP_QUOTE", "books": books}

    ref = max(priced, key=lambda k: (weights[k], k))
    result = {"books": books, "reference_book": ref, "reference_line": priced[ref]["line"],
              "line_clv_pts": priced[ref].get("line_clv_pts")}
    usable = {k: b for k, b in priced.items() if "prob_at_taken_line" in b}
    total_w = sum(weights[k] for k in usable)
    if total_w < policy["min_sharp_weight"]:
        result.update(status="LINE_ONLY", reason="LINE_MOVED_NO_CONVERSION")
        return result
    probs = [b["prob_at_taken_line"] for b in usable.values()]
    if (max(probs) - min(probs)) * 100 > policy["max_sharp_dispersion_pp"]:
        result.update(status="UNAVAILABLE", reason="SHARP_DISAGREEMENT")
        return result
    fair = sum(weights[k] * b["prob_at_taken_line"] for k, b in usable.items()) / total_w
    same = {k: b for k, b in usable.items() if b["prob_method"] == "SAME_LINE"}
    same_w = sum(weights[k] for k in same)
    taken = float(play["price_decimal"])
    result.update(
        status="GRADED",
        reference_label="CONSENSUS" if len(usable) >= policy["min_books_for_consensus_label"] else f"{next(iter(usable)).upper()}_ONLY",
        fair_p_at_taken_line=round(fair, 6),
        prob_clv_pp=round(100 * (fair - 1 / taken), 3),
        prob_clv_method="SAME_LINE" if len(same) == len(usable) else conv["method"],
        same_line_price_clv_pp=(round(100 * (sum(weights[k] * b["prob_at_taken_line"] for k, b in same.items()) / same_w - 1 / taken), 3)
                                if same and same_w >= policy["min_sharp_weight"] else None),
        per_book_clv_pp={k: round(100 * (b["prob_at_taken_line"] - 1 / taken), 3) for k, b in usable.items()},
    )
    return result


# ---------- statistics ----------

def _betacf(a, b, x):
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c if abs(1 + aa / c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c if abs(1 + aa / c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-14:
            break
    return h


def _betainc(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return bt * _betacf(a, b, x) / a
    return 1 - bt * _betacf(b, a, 1 - x) / b


def t_cdf(t: float, df: float) -> float:
    tail = 0.5 * _betainc(df / 2, 0.5, df / (df + t * t))
    return 1 - tail if t > 0 else tail


def t_ppf(q: float, df: float) -> float:
    lo, hi = -1e4, 1e4
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if t_cdf(mid, df) < q else (lo, mid)
    return (lo + hi) / 2


def clv_stats(rows: list, one_sided_confidence: float = 0.975) -> dict:
    """Mean CLV with the CR1 cluster-robust SE for an intercept-only model
    (K=1, so the (N-1)/(N-K) factor is 1), clustered by slate_date.
    Lower bound uses Student t with G-1 degrees of freedom."""
    n = len(rows)
    clusters = {}
    for r in rows:
        clusters.setdefault(r["slate_date"], []).append(float(r["clv_pp"]))
    g = len(clusters)
    out = {"graded": n, "slate_clusters": g, "mean_clv_pp": None, "se_pp": None,
           "t_stat": None, "df": None, "lower_bound_pp": None}
    if n == 0:
        return out
    mean = sum(float(r["clv_pp"]) for r in rows) / n
    out["mean_clv_pp"] = mean
    if g >= 2:
        s = sum(sum(x - mean for x in xs) ** 2 for xs in clusters.values())
        var = (g / (g - 1)) * s / (n * n)
        if var > 0:
            se = math.sqrt(var)
            out.update(se_pp=se, t_stat=mean / se, df=g - 1,
                       lower_bound_pp=mean - t_ppf(one_sided_confidence, g - 1) * se)
    return out


def source_stage(graded_rows: list, eligible: int, staging: dict, sport_key: str) -> dict:
    """Stage for one source + sport_key bucket. Sports are never pooled."""
    promo, demote = staging["promote_to_standard"], staging["demote_to_paper"]
    stats = clv_stats(graded_rows, promo["lower_bound"]["one_sided_confidence"])
    coverage = (stats["graded"] / eligible) if eligible else None
    stage = staging["start"]
    mean, lb = stats["mean_clv_pp"], stats["lower_bound_pp"]
    if stats["graded"] >= demote["min_graded"] and mean is not None and mean < demote["mean_clv_pp_below"]:
        stage = "PAPER"
    elif (stats["graded"] >= promo["min_graded"] and stats["slate_clusters"] >= promo["min_slate_clusters"]
          and coverage is not None and coverage >= promo["min_close_coverage"]
          and mean is not None and mean >= promo["min_mean_clv_pp"]
          and lb is not None and lb > promo["lower_bound"]["must_exceed_pp"]):
        stage = "STANDARD"
    capped_by = None
    cap = staging.get("max_stage_by_sport", {}).get(sport_key)
    order = staging["stage_order"]
    if cap is not None and order.index(stage) > order.index(cap):
        stage, capped_by = cap, "MAX_STAGE_BY_SPORT"
    return dict(stats, eligible=eligible, coverage=coverage, stage=stage, capped_by=capped_by,
                units=staging["units"][stage], sport_key=sport_key)
