"""Forward evaluator — NBA Team Totals Forward Test V1.

Implements the FROZEN preregistration
`PREREG_NBA_TEAM_TOTALS_FORWARD_V1_DRAFT.md` (sha256 pinned below; frozen
2026-10-22 21:34:21 CT). Section references (§) are to that document.
Ambiguities are resolved conservatively; each resolution is listed in
`EVALUATOR_NOTES.md` beside this file (tag "A<n>" in comments).

Pure function of committed records. No network, no market data fetch,
no backfill. PLAY is impossible: output carries no stake or eligibility.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
FROZEN_DOC = HERE / "PREREG_NBA_TEAM_TOTALS_FORWARD_V1_DRAFT.md"
FROZEN_DOC_SHA256 = (
    "0274e8cd248ed56a43c445c3d23e96e04eb218f4abcafb2ebe4041448ef55504")
ENGINE_ID = "NBA_TEAM_PERIOD_RATINGS_V1"
PINNED_ENGINE_SHA256 = (
    "9060b972f9d1f69696db7f75569ab175884e02ff7b6ea81fb9817c6f390bc6de")
PINNED_RUNNER_SHA256 = (
    "28edafba1e41baa4e0485d9c14542d4c8ba56d2a3913a8d22a546541fb13cbe2")

ALPHA = 0.05
FROZEN_SEED = 20261022
FROZEN_K = 9
FROZEN_RESAMPLES = 10_000
PICK_GAP = 2.0
CLOSE_WINDOW_S = 3600
CLOSE_PAIR_SPAN_S = 150
ENTRY_PAIR_SPAN_S = 120
FRESH_S = 180
GATES = {"full_slates": 4, "valid_clv_rows": 150, "games": 40, "picked": 50}
VOID_STATUSES = {"POSTPONED", "SUSPENDED", "CANCELLED", "CANCELED", "VOID"}

RUNNER_REFUSALS = {
    "DK_PAIR_MISSING_OR_STALE", "TWO_SIDED_OU_REQUIRED",
    "DRAFTKINGS_QUOTE_REQUIRED", "FINITE_DK_ODDS_REQUIRED",
    "NATIVE_TWO_SIDED_QUOTES_REQUIRED", "DK_PAIR_CAPTURE_SPAN_EXCEEDED",
}
ENGINE_REFUSALS = {
    "NBA_TEAM_PERIOD_TEAM_NOT_IN_HISTORY",
    "NBA_TEAM_PERIOD_INSUFFICIENT_TEAM_PRIORS",
    "NBA_TEAM_PERIOD_INSUFFICIENT_LEAGUE_PRIORS",
    "NBA_TEAM_PERIOD_TARGET_INVALID", "NBA_FIXTURE_IDENTITY_INCOMPLETE",
    "NBA_TEAM_SELECTION_UNBOUND", "NBA_ENGINE_FAILED",
}
EVAL_REFUSALS = {
    "MARKET_OUT_OF_SCOPE", "ENTRY_NOT_PRETIP", "ENTRY_SINGLE_SIDED",
    "PRICE_INVALID", "ENGINE_PROVENANCE_MISSING", "HISTORY_HASH_MISMATCH",
    "QUOTE_STALE_180S",
}
DECLARED_REFUSALS = RUNNER_REFUSALS | ENGINE_REFUSALS | EVAL_REFUSALS
CLV_MISSING = {"NO_CLOSE_ROW", "LINE_MOVED", "CLOSE_SINGLE_SIDED",
               "CLOSE_NOT_PRETIP", "CLOSE_STALE", "PAIR_SPAN_EXCEEDED",
               "QUOTE_STALE_180S"}


def verify_frozen_doc() -> bool:
    h = hashlib.sha256(FROZEN_DOC.read_bytes()).hexdigest()
    if h != FROZEN_DOC_SHA256:
        raise RuntimeError(f"FROZEN_DOC_HASH_MISMATCH {h}")
    return True


def _t(s):
    t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("TIMESTAMP_WITHOUT_ZONE")
    return t


def _price_ok(p):
    if isinstance(p, bool) or not isinstance(p, (int, float)):
        return False
    return math.isfinite(p) and abs(p) >= 100


def _imp(p):
    return 100.0 / (p + 100.0) if p > 0 else -p / (-p + 100.0)


def no_vig(over_price, under_price):
    """Multiplicative two-sided de-vig; returns P(OVER). For whole-number
    lines this is the push-removed (conditional on no push) probability
    (§6d; A6)."""
    a, b = _imp(over_price), _imp(under_price)
    return a / (a + b)


def classify(gap):
    """§5 pick rule; side is sign(gap) (§6c), None at gap 0."""
    side = "OVER" if gap > 0 else ("UNDER" if gap < 0 else None)
    if gap >= PICK_GAP or gap <= -PICK_GAP:
        return ("PICKED", side)
    return ("PASSED", side)


def ci_level(k):
    return 1.0 - ALPHA / k


def sign_test_p(adverse, n):
    """One-sided exact sign test P(X >= adverse | n, 1/2); None if n == 0
    (zero moved picked rows: not run, §6 rule 1)."""
    if n == 0:
        return None
    return sum(math.comb(n, i) for i in range(adverse, n + 1)) / 2.0 ** n


def select_entry(quotes, game, team):
    """§5: first DK ENTRY capture for the game/team at the main line."""
    cands = [q for q in quotes if q.get("game_id") == game
             and q.get("team") == team and q.get("designation") == "ENTRY"
             and q.get("book") == "DraftKings" and q.get("is_main") is True]
    if not cands:
        return None
    caps = defaultdict(list)
    for q in cands:
        caps[q.get("capture_id")].append(q)
    first = min(caps.values(), key=lambda g: min(_t(q["captured_at"])
                                                 for q in g))
    by_line = defaultdict(dict)
    for q in first:
        by_line[q.get("line")][q.get("side")] = q
    two = [ln for ln, s in by_line.items() if {"OVER", "UNDER"} <= set(s)]
    if len(two) != 1:  # A2: none or several main lines -> not a clean entry
        return {"line": None, "capture_id": first[0].get("capture_id"),
                "sides": None}
    ln = two[0]
    return {"line": ln, "capture_id": first[0].get("capture_id"),
            "sides": by_line[ln]}


def move_direction(side, entry_line, lines):
    """§6c: direction vs the picked side; straddle = ADVERSE."""
    up = all(x > entry_line for x in lines)
    down = all(x < entry_line for x in lines)
    if side == "OVER":
        return "FAVORABLE" if up else "ADVERSE"
    return "FAVORABLE" if down else "ADVERSE"


def close_status(closes, game, team, entry_line, tip):
    """§7: the close is the LAST capture before tipoff (A3)."""
    out = {"reason": None, "moved": False, "close_line": None,
           "close_lines": [], "p_over": None}
    cands = [c for c in closes if c.get("game_id") == game
             and c.get("team") == team and c.get("designation") == "CLOSE"
             and c.get("book") == "DraftKings"]
    if not cands:
        return {**out, "reason": "NO_CLOSE_ROW"}
    caps = defaultdict(list)
    for c in cands:
        caps[c.get("capture_id")].append(c)
    pre = [g for g in caps.values()
           if all(_t(c["captured_at"]) < tip for c in g)]
    if not pre:
        return {**out, "reason": "CLOSE_NOT_PRETIP"}
    last = max(pre, key=lambda g: max(_t(c["captured_at"]) for c in g))
    earliest = min(_t(c["captured_at"]) for c in last)
    if (tip - earliest).total_seconds() > CLOSE_WINDOW_S:
        return {**out, "reason": "CLOSE_STALE"}
    by_line = defaultdict(dict)
    for c in last:
        by_line[c.get("line")][c.get("side")] = c
    valid, span_bad = {}, set()
    for ln, s in by_line.items():
        if not {"OVER", "UNDER"} <= set(s):
            continue
        o, u = s["OVER"], s["UNDER"]
        if not (_price_ok(o.get("price")) and _price_ok(u.get("price"))):
            continue  # A4: unpriceable side = not two-sided
        if abs((_t(o["captured_at"]) - _t(u["captured_at"]))
               .total_seconds()) > CLOSE_PAIR_SPAN_S:
            span_bad.add(ln)
            continue
        valid[ln] = no_vig(o["price"], u["price"])
    if entry_line in valid:
        return {**out, "close_line": entry_line, "close_lines": [entry_line],
                "p_over": valid[entry_line]}
    if entry_line in span_bad:
        return {**out, "reason": "PAIR_SPAN_EXCEEDED"}
    if valid:
        lines = sorted(valid)
        # A5: 6a close line among several = the one nearest 50/50
        cl = min(lines, key=lambda x: (abs(valid[x] - 0.5),
                                       abs(x - entry_line)))
        return {**out, "moved": True, "close_line": cl, "close_lines": lines,
                "p_over": valid[cl]}
    if span_bad:
        return {**out, "reason": "PAIR_SPAN_EXCEEDED"}
    return {**out, "reason": "CLOSE_SINGLE_SIDED"}


def _norm_engine_code(code):
    c = str(code)
    if c.startswith("NBA_ENGINE_FAILED"):
        return "NBA_ENGINE_FAILED"
    if c.startswith("NBA_ENGINE_") and c[len("NBA_ENGINE_"):] in \
            ENGINE_REFUSALS:
        return c[len("NBA_ENGINE_"):]
    return c


def _row_check(r, entry_quotes):
    """Returns (refusal_code | None, entry, mean)."""
    if r.get("market", "TEAM_TOTAL") != "TEAM_TOTAL":
        return "MARKET_OUT_OF_SCOPE", None, None
    if r.get("runner_refusal"):
        return _norm_engine_code(r["runner_refusal"]), None, None
    eng = r.get("engine") or {}
    if eng.get("status") == "REFUSED":
        return _norm_engine_code(eng.get("reason")), None, None
    mean = eng.get("mean")
    if (eng.get("engine_id") != ENGINE_ID or eng.get("status") != "PRICED"
            or eng.get("sufficiency_met") is not True
            or not isinstance(mean, (int, float)) or not math.isfinite(mean)
            or not eng.get("priors")):
        return "ENGINE_PROVENANCE_MISSING", None, None
    # A7: any pin mismatch fails the run-record proof (§11)
    if (r.get("engine_sha256") != PINNED_ENGINE_SHA256
            or r.get("runner_sha256") != PINNED_RUNNER_SHA256
            or r.get("history_hash_recorded_before_pricing") is not True):
        return "HISTORY_HASH_MISMATCH", None, None
    if r.get("team") not in (r.get("home"), r.get("away")):
        return "NBA_TEAM_SELECTION_UNBOUND", None, None
    e = select_entry(entry_quotes, r["game_id"], r["team"])
    if e is None:
        return "DK_PAIR_MISSING_OR_STALE", None, None
    if e["line"] is None:
        return "ENTRY_SINGLE_SIDED", None, None
    o, u = e["sides"]["OVER"], e["sides"]["UNDER"]
    if not (_price_ok(o.get("price")) and _price_ok(u.get("price"))) or \
            not isinstance(e["line"], (int, float)):
        return "PRICE_INVALID", None, None
    to, tu, tip = _t(o["captured_at"]), _t(u["captured_at"]), _t(r["tipoff"])
    if to >= tip or tu >= tip:
        return "ENTRY_NOT_PRETIP", None, None
    if abs((to - tu).total_seconds()) > ENTRY_PAIR_SPAN_S:
        return "DK_PAIR_CAPTURE_SPAN_EXCEEDED", None, None
    if (_t(r["priced_at"]) - min(to, tu)).total_seconds() > FRESH_S:
        return "QUOTE_STALE_180S", None, None
    return None, e, float(mean)


def _cluster_ci(values, clusters, seed, resamples, k):
    vals = np.asarray(values, float)
    ids = {c: i for i, c in enumerate(dict.fromkeys(clusters))}
    g = np.array([ids[c] for c in clusters])
    G = len(ids)
    sums = np.bincount(g, weights=vals, minlength=G)
    cnts = np.bincount(g, minlength=G).astype(float)
    rng = np.random.default_rng(seed)  # A8: fresh seeded stream per metric
    idx = rng.integers(0, G, size=(resamples, G))
    bs = sums[idx].sum(1) / cnts[idx].sum(1)
    a = ALPHA / k
    return {"n": int(len(vals)), "games": G, "mean": float(vals.mean()),
            "lo": float(np.quantile(bs, a / 2)),
            "hi": float(np.quantile(bs, 1 - a / 2)), "level": ci_level(k)}


def evaluate(rows, entry_quotes, close_quotes, results, slates,
             missing_offers, config):
    first = config.get("first_counted_slate")
    if not first:
        raise ValueError("FIRST_COUNTED_SLATE_REQUIRED")
    k = int(config.get("k", FROZEN_K))
    seed = int(config.get("seed", FROZEN_SEED))
    B = int(config.get("resamples", FROZEN_RESAMPLES))
    out = {"evaluator": "EVAL_NBA_TEAM_TOTALS_V1",
           "frozen_doc_sha256": FROZEN_DOC_SHA256,
           "k": k, "clock_ids": config.get("clock_ids"), "seed": seed,
           "resamples": B,
           "binding": (k >= FROZEN_K and seed == FROZEN_SEED
                       and B == FROZEN_RESAMPLES),
           "play_authority": False, "eligible": False}
    refusals, excluded, clv_missing = Counter(), Counter(), Counter()
    undeclared = Counter()
    counts = Counter(engine_priced_rows=0, historical_not_counted=0)
    recs = []
    for r in rows:
        if str(r.get("slate_date")) < str(first):
            counts["historical_not_counted"] += 1
            continue
        code, e, mean = _row_check(r, entry_quotes)
        if code:
            if code in DECLARED_REFUSALS:
                refusals[code] += 1
            else:
                undeclared[code] += 1
            continue
        counts["engine_priced_rows"] += 1
        res = results.get(r["game_id"])
        status = (res or {}).get("status")
        if status in VOID_STATUSES:
            excluded["VOID"] += 1
            continue
        y = ((res or {}).get("points") or {}).get(r["team"])
        if status != "FINAL" or not isinstance(y, (int, float)):
            excluded["RESULT_UNAVAILABLE"] += 1
            continue
        line = float(e["line"])
        gap = mean - line
        grp, side = classify(gap)
        cs = close_status(close_quotes, r["game_id"], r["team"], line,
                          _t(r["tipoff"]))
        if cs["reason"]:
            clv_missing[cs["reason"]] += 1
        elif cs["moved"]:
            clv_missing["LINE_MOVED"] += 1
        if gap == 0:
            excluded["GAP_ZERO"] += 1
        if y == line:
            excluded["PUSH"] += 1
        p_entry = no_vig(e["sides"]["OVER"]["price"],
                         e["sides"]["UNDER"]["price"])
        recs.append({"slate": str(r["slate_date"]), "game": r["game_id"],
                     "y": float(y), "mean": mean, "line": line, "gap": gap,
                     "group": grp, "side": side, "close": cs,
                     "p_entry_over": p_entry,
                     "b1": float(r["engine"]["b1_team_mean"]),
                     "b2": float(r["engine"]["b2_league_mean"])})
    out.update({"refusals": dict(refusals), "excluded": dict(excluded),
                "clv_missing": dict(clv_missing),
                "undeclared_codes": dict(undeclared),
                "missing_offer": {"count": len(missing_offers),
                                  "items": list(missing_offers)}})
    if undeclared:
        out.update(counts=dict(counts), verdict="UNDECLARED_REFUSAL_CODE",
                   verdict_reason="UNDECLARED_REFUSAL_CODE")
        return out
    # §4: single review at the first slate close where all gates are met
    dates = sorted({x["slate"] for x in recs})
    full = {d for d, s in (slates or {}).items() if str(d) >= str(first)
            and s.get("entry_job_ok") and s.get("close_job_ok")
            and s.get("all_games_captured")}
    review = None
    for d in dates:
        cum = [x for x in recs if x["slate"] <= d]
        g = {
            "full_slates": len([f for f in full if f <= d]),
            "valid_clv_rows": sum(1 for x in cum if not x["close"]["reason"]
                                  and not x["close"]["moved"]),
            "games": len({x["game"] for x in cum}),
            "picked": sum(1 for x in cum if x["group"] == "PICKED"),
        }
        if all(g[n] >= GATES[n] for n in GATES):
            review, gates_at = d, g
            break
    if review is None:
        counts["full_slates"] = len(full)
        out.update(counts=dict(counts), verdict="INSUFFICIENT_SAMPLE",
                   verdict_reason="GATES_NOT_MET", review_slate=None)
        return out  # no primary metrics before the review (§4, §12)
    S = [x for x in recs if x["slate"] <= review]
    counts["full_slates"] = gates_at["full_slates"]
    counts["sample_rows"] = len(S)  # scoreable rows through review slate
    out["review_slate"] = review
    out["gates_at_review"] = gates_at
    m = {}
    picked = [x for x in S if x["group"] == "PICKED" and x["side"]]
    pv = [x for x in picked if not x["close"]["reason"]]
    pm = [x for x in pv if x["close"]["moved"]]
    adverse = sum(1 for x in pm if move_direction(
        x["side"], x["line"], x["close"]["close_lines"]) == "ADVERSE")
    p = sign_test_p(adverse, len(pm))
    m["moved"] = {"picked_moved": len(pm), "adverse": adverse,
                  "favorable": len(pm) - adverse, "sign_test_run": p is not None,
                  "p_one_sided": p, "threshold": ALPHA / k}
    invalid = sum(1 for x in S if x["close"]["reason"])
    m["invalid_close_share"] = invalid / len(S) if S else 1.0
    m["picked_moved_share"] = len(pm) / len(pv) if pv else 0.0
    out["metrics"] = m
    out["counts"] = dict(counts)
    # §6 order (A1): sign test, then >20% invalid, then >50% moved picks
    if p is not None and p < ALPHA / k:
        out.update(verdict="DOES_NOT_BEAT_MARKET",
                   verdict_reason="MOVED_SIGN_TEST_ADVERSE")
        return out
    if m["invalid_close_share"] > 0.20:
        out.update(verdict="INSUFFICIENT_CLOSE_DATA",
                   verdict_reason="INVALID_CLOSE_OVER_20PCT")
        return out
    if m["picked_moved_share"] > 0.50:
        out.update(verdict="INSUFFICIENT_CLOSE_DATA",
                   verdict_reason="PICKED_MOVED_OVER_50PCT")
        return out
    V = [x for x in S if not x["close"]["reason"]]
    cl = [x["game"] for x in V]
    ci = lambda vals, cls, tag: _cluster_ci(  # noqa: E731
        vals, cls, seed, B, k) if vals else None
    a = ci([abs(x["mean"] - x["y"]) - abs(x["close"]["close_line"] - x["y"])
            for x in V], cl, "6a")
    m["6a"] = {"dMAE_vs_close": a, "pass": bool(a and a["hi"] < 0),
               "rmse_engine": float(np.sqrt(np.mean(
                   [(x["mean"] - x["y"]) ** 2 for x in V]))) if V else None,
               "rmse_close": float(np.sqrt(np.mean(
                   [(x["close"]["close_line"] - x["y"]) ** 2 for x in V])))
               if V else None}
    b1 = ci([abs(x["mean"] - x["y"]) - abs(x["b1"] - x["y"]) for x in V],
            cl, "6b1")
    b2 = ci([abs(x["mean"] - x["y"]) - abs(x["b2"] - x["y"]) for x in V],
            cl, "6b2")
    m["6b"] = {"vs_team_mean": b1, "vs_league_mean": b2,
               "pass": bool(b1 and b2 and b1["hi"] < 0 and b2["hi"] < 0)}

    def clv(x):
        po = x["close"]["p_over"]
        return (po - x["p_entry_over"]) if x["side"] == "OVER" else \
            ((1 - po) - (1 - x["p_entry_over"]))
    E = [x for x in V if not x["close"]["moved"] and x["side"]]
    Pk = [x for x in E if x["group"] == "PICKED"]
    Ps = [x for x in E if x["group"] == "PASSED"]
    c6 = {"picked": ci([clv(x) for x in Pk], [x["game"] for x in Pk], "6c"),
          "passed_mean": float(np.mean([clv(x) for x in Ps])) if Ps else None}
    if not Pk:
        c6.update(pass_=False, reason="NO_PICKED_ROWS")
    elif not Ps:
        c6.update(pass_=False, reason="NO_PASSED_ROWS")  # A9
    else:
        ok = c6["picked"]["lo"] > 0 and c6["picked"]["mean"] > \
            c6["passed_mean"]
        c6.update(pass_=bool(ok), reason=None if ok else "CLV_LEG_FAILED")
    c6["pass"] = c6.pop("pass_")
    m["6c"] = c6
    D = [x for x in Pk if x["y"] != x["line"]]

    def hit_minus_p(x):
        po = x["close"]["p_over"]
        hit = (x["y"] > x["line"]) if x["side"] == "OVER" else \
            (x["y"] < x["line"])
        return float(hit) - (po if x["side"] == "OVER" else 1 - po)
    d = ci([hit_minus_p(x) for x in D], [x["game"] for x in D], "6d")
    m["6d"] = {"hit_minus_pclose": d, "pushes_excluded":
               len(Pk) - len(D), "pass": bool(d and d["lo"] > 0)}
    ok = all(m[s]["pass"] for s in ("6a", "6b", "6c", "6d"))
    out.update(verdict="BEATS_MARKET" if ok else "DOES_NOT_BEAT_MARKET",
               verdict_reason=None if ok else "PRIMARY_LEG_FAILED:" + ",".join(
                   s for s in ("6a", "6b", "6c", "6d") if not m[s]["pass"]))
    return out
