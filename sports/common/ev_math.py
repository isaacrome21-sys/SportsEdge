"""EV tracker math. Fair prices are MARKET_FAIR_P from sharp books.
Never Model_P, never Truth Gate input. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")


class EVError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def load_policy(path) -> dict:
    raw = Path(path).read_bytes()
    policy = json.loads(raw)
    if policy.get("policy_id") != "EV_TRACKER_POLICY_V1":
        raise EVError("EV_POLICY_ID_MISMATCH")
    policy["_sha256"] = hashlib.sha256(raw).hexdigest()
    return policy


def parse_utc(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
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
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
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
        if sum(probs(mid)) - 1 > 0:
            lo = mid
        else:
            hi = mid
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


# ---------- event matching ----------

def team_matches(user_text: str, full_name: str) -> bool:
    a, b = user_text.strip().lower(), full_name.strip().lower()
    if not a:
        return False
    return a == b or b.endswith(" " + a) or (len(a) >= 4 and a in b)


def match_event(events: list, away: str, home: str, now: datetime, game_date_ct: str = None) -> dict:
    """Returns {"event": ..., "swapped": bool}. Only games not yet started."""
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
        return sorted(out, key=lambda e: e["commence_time"])

    for swapped, (a, h) in ((False, (away, home)), (True, (home, away))):
        found = candidates(a, h)
        if not found:
            continue
        if game_date_ct and len(found) > 1:
            raise EVError("EVENT_AMBIGUOUS", f"{len(found)} games match")
        ids = {(e["away_team"], e["home_team"]) for e in found}
        if len(ids) > 1:
            raise EVError("EVENT_AMBIGUOUS", "team names match more than one matchup")
        return {"event": found[0], "swapped": swapped}
    raise EVError("EVENT_NOT_FOUND", f"{away} at {home}")


# ---------- sharp fair price ----------

def _two_sides(outcomes, play):
    market, pick, line = play["market"], play["pick"], play.get("line")
    if market == "h2h":
        if len(outcomes) != 2:
            return None, False
        mine = [o for o in outcomes if o["name"] == pick]
        other = [o for o in outcomes if o["name"] != pick]
    elif market == "spreads":
        other_team = play["home_team"] if pick == play["away_team"] else play["away_team"]
        listed = any(o["name"] == pick for o in outcomes)
        mine = [o for o in outcomes if o["name"] == pick and float(o.get("point", 1e9)) == float(line)]
        other = [o for o in outcomes if o["name"] == other_team and float(o.get("point", 1e9)) == -float(line)]
        if not (len(mine) == 1 and len(other) == 1):
            return None, listed
    elif market == "totals":
        opposite = "Under" if pick == "Over" else "Over"
        listed = any(o["name"] == pick for o in outcomes)
        mine = [o for o in outcomes if o["name"] == pick and float(o.get("point", -1)) == float(line)]
        other = [o for o in outcomes if o["name"] == opposite and float(o.get("point", -1)) == float(line)]
        if not (len(mine) == 1 and len(other) == 1):
            return None, listed
    else:
        raise EVError("MARKET_UNSUPPORTED", market)
    if len(mine) != 1 or len(other) != 1:
        return None, bool(mine)
    return (float(mine[0]["price"]), float(other[0]["price"])), True


def sharp_fair_for_play(event_odds: dict, play: dict, policy: dict, fetched_at: datetime) -> dict:
    weights = policy["sharp_weights"]
    dv = policy["devig"]
    per_book, line_moved = {}, False
    for bk in event_odds.get("bookmakers", []):
        key = bk.get("key")
        if key not in weights or key == play["book"]:
            continue
        for mk in bk.get("markets", []):
            if mk.get("key") != play["market"]:
                continue
            stamp = mk.get("last_update") or bk.get("last_update")
            if not stamp or (fetched_at - parse_utc(stamp)).total_seconds() > policy["max_quote_age_s"]:
                continue
            sides, listed = _two_sides(mk.get("outcomes", []), play)
            if sides is None:
                line_moved = line_moved or listed
                continue
            try:
                per_book[key] = devig(list(sides), dv["sensitivity_trigger_american"], dv["max_method_spread_pp"])[0]
            except EVError as exc:
                return {"status": "UNAVAILABLE", "reason": exc.code}
    total_w = sum(weights[b] for b in per_book)
    if total_w < policy["min_sharp_weight"]:
        return {"status": "UNAVAILABLE", "reason": "LINE_MOVED_AT_SHARP_BOOKS" if line_moved else "NO_SHARP_REFERENCE"}
    vals = list(per_book.values())
    if (max(vals) - min(vals)) * 100 > policy["max_sharp_dispersion_pp"]:
        return {"status": "UNAVAILABLE", "reason": "SHARP_DISAGREEMENT"}
    fair = sum(weights[b] * p for b, p in per_book.items()) / total_w
    return {"status": "OK", "fair_p": fair, "books": per_book}


def clv_pp(taken_decimal: float, fair_p: float) -> float:
    return 100.0 * (fair_p - 1.0 / taken_decimal)


# ---------- staging ----------

def clv_stats(rows: list) -> dict:
    n = len(rows)
    clusters = {}
    for r in rows:
        clusters.setdefault(r["slate_date"], []).append(float(r["clv_pp"]))
    g = len(clusters)
    out = {"graded": n, "slate_clusters": g, "mean_clv_pp": None, "clv_t_stat": None}
    if n == 0:
        return out
    mean = sum(float(r["clv_pp"]) for r in rows) / n
    out["mean_clv_pp"] = mean
    if n >= 2 and g >= 2:
        s = sum(sum(x - mean for x in xs) ** 2 for xs in clusters.values())
        var = (g / (g - 1)) * s / (n * n)
        if var > 0:
            out["clv_t_stat"] = mean / math.sqrt(var)
    return out


def source_stage(rows: list, staging: dict) -> dict:
    stats = clv_stats(rows)
    stage = staging["start"]
    d, p = staging["demote_to_paper"], staging["promote_to_standard"]
    mean, t = stats["mean_clv_pp"], stats["clv_t_stat"]
    if stats["graded"] >= d["min_graded"] and mean is not None and mean < d["mean_clv_pp_below"]:
        stage = "PAPER"
    elif (stats["graded"] >= p["min_graded"] and stats["slate_clusters"] >= p["min_slate_clusters"]
          and mean is not None and t is not None
          and mean >= p["min_mean_clv_pp"] and t >= p["min_clv_t_stat"]):
        stage = "STANDARD"
    return dict(stats, stage=stage, units=staging["units"][stage])
