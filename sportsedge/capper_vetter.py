"""CAPPER_VETTER_V1 — grade outside pick posters (cappers) on process.

Add-on to the EXTERNAL_EV lane. It never produces picks and never feeds
Model_P or the Truth Gate; it only scores outside accounts so the owner
can decide whom to cross-check, paper-trade or ignore.

Input: one dict per logged pick (from "[CAPPER]" issues), fields:
  account, posted_at (ISO), tip_utc (ISO), sport, market, selection,
  line, price (American, at post time), close_price (American, same
  side + same line, optional), close_other_price (opposite side at
  close, optional, used to de-vig), result ("win"|"loss"|"push"|
  "pending"), units (optional, default 1.0), shows_losses (bool,
  optional, account-level honesty flag copied onto each pick).

Score (0-100) = weighted mean of sub-scores; weights, shrinkage and
red-flag rules live in config/capper_vetter_v1.json.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

ENGINE_ID = "CAPPER_VETTER_V1"
DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "capper_vetter_v1.json"


def load_config(path=None) -> dict:
    return json.loads(Path(path or DEFAULT_CONFIG).read_text(encoding="utf-8"))


def implied(price: float) -> float:
    price = float(price)
    return -price / (-price + 100.0) if price < 0 else 100.0 / (price + 100.0)


def payout(price: float) -> float:
    price = float(price)
    return 100.0 / -price if price < 0 else price / 100.0


def _ts(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def clv_pct(pick: dict, default_vig: float) -> float | None:
    """Fair close probability minus entry implied probability, in
    percentage points. De-vigs with the opposite side when present,
    otherwise removes half of ``default_vig`` from the close side."""
    cp = pick.get("close_price")
    if cp is None:
        return None
    p_close = implied(cp)
    other = pick.get("close_other_price")
    if other is not None:
        p_close = p_close / (p_close + implied(other))
    else:
        p_close = p_close - default_vig / 2.0
    return (p_close - implied(pick["price"])) * 100.0


def max_drawdown(pnls: list[float]) -> float:
    peak = run = dd = 0.0
    for x in pnls:
        run += x
        peak = max(peak, run)
        dd = max(dd, peak - run)
    return dd


def _scale(x: float, lo: float, hi: float) -> float:
    if hi == lo:
        return 0.0
    return max(0.0, min(100.0, (x - lo) / (hi - lo) * 100.0))


def grade_account(picks: list[dict], cfg: dict) -> dict:
    flags: list[str] = []
    late = [p for p in picks
            if _ts(p.get("posted_at")) is None or _ts(p.get("tip_utc")) is None
            or _ts(p["posted_at"]) >= _ts(p["tip_utc"])]
    if late:
        flags.append(f"POSTED_AFTER_TIP_OR_UNTIMED:{len(late)}")
    late_ids = {id(p) for p in late}
    valid = [p for p in picks if id(p) not in late_ids]
    graded = [p for p in valid if p.get("result") in ("win", "loss", "push")]

    risked = pnl_sum = 0.0
    pnls: list[float] = []
    for p in graded:
        u = float(p.get("units") or 1.0)
        risked += u
        x = u * payout(p["price"]) if p["result"] == "win" else (-u if p["result"] == "loss" else 0.0)
        pnls.append(x)
        pnl_sum += x
    n = len(graded)
    roi = pnl_sum / risked if risked else 0.0
    k, prior = cfg["shrinkage_k"], cfg["prior_roi"]
    adj_roi = (n / (n + k)) * roi + (k / (n + k)) * prior

    clvs = [c for c in (clv_pct(p, cfg["default_vig"]) for p in valid) if c is not None]
    clv = sum(clvs) / len(clvs) if clvs else None
    close_cov = len(clvs) / len(valid) if valid else 0.0
    if clv is not None and len(clvs) >= cfg["clv_min_for_flag"] and clv < 0:
        flags.append("NEGATIVE_CLV")
    if any(p.get("shows_losses") is False for p in picks):
        flags.append("HIDES_LOSSES")
    units = [float(p.get("units") or 1.0) for p in valid]
    if units and max(units) > cfg["max_reasonable_units"]:
        flags.append("EXTREME_UNITS")

    s = cfg["scales"]
    sub = {
        "clv": _scale(clv, *s["clv_pct"]) if clv is not None else 0.0,
        "adj_roi": _scale(adj_roi, *s["adj_roi"]),
        "sample": _scale(math.log1p(n), 0.0, math.log1p(s["sample_full"])),
        "transparency": 100.0 * (len(valid) / len(picks) if picks else 0.0) * (0.5 + 0.5 * close_cov),
        "risk": 100.0 - _scale(max_drawdown(pnls), *s["drawdown_units"]),
    }
    w = cfg["weights"]
    score = sum(sub[key] * w[key] for key in w) / sum(w.values())
    for f in flags:
        name = f.split(":")[0]
        if name in cfg["auto_fail_flags"]:
            score = 0.0
        else:
            score -= cfg["flag_penalty"]
    score = max(0.0, min(100.0, score))
    return {
        "engine": ENGINE_ID, "account": picks[0]["account"] if picks else None,
        "picks_logged": len(picks), "picks_graded": n,
        "roi": round(roi, 4), "adj_roi": round(adj_roi, 4),
        "clv_pct": None if clv is None else round(clv, 3),
        "close_coverage": round(close_cov, 3),
        "max_drawdown_units": round(max_drawdown(pnls), 2),
        "subscores": {k2: round(v, 1) for k2, v in sub.items()},
        "flags": flags, "score": round(score, 1),
        "grade": next(g for cut, g in cfg["grades"] if score >= cut),
    }


def rank(all_picks: list[dict], cfg: dict | None = None) -> list[dict]:
    cfg = cfg or load_config()
    by: dict[str, list[dict]] = {}
    for p in all_picks:
        by.setdefault(p["account"], []).append(p)
    rows = [grade_account(ps, cfg) for ps in by.values()]
    return sorted(rows, key=lambda r: r["score"], reverse=True)


if __name__ == "__main__":  # python -m sportsedge.capper_vetter picks.jsonl
    import sys
    picks = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines() if line.strip()]
    for r in rank(picks):
        print(f"{r['score']:5.1f} {r['grade']:>2}  {r['account']:<20} n={r['picks_graded']:<4} "
              f"CLV={r['clv_pct']}  adjROI={r['adj_roi']:+.3f}  {','.join(r['flags'])}")
