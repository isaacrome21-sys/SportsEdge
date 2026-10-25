"""Shared scoring helpers for the 2026-10-24 overnight backtests (#2447).

Stdlib + numpy only. No model math lives here; only evaluation arithmetic.
"""
from __future__ import annotations

import hashlib
import math

import numpy as np

EV_THRESHOLD = 0.02
MIN_N_FOR_VERDICT = 200


def git_blob_sha1(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def american_to_decimal(o: float) -> float:
    return 1.0 + o / 100.0 if o > 0 else 1.0 + 100.0 / abs(o)


def implied(o: float) -> float:
    return 1.0 / american_to_decimal(o)


def no_vig(a: float, b: float) -> tuple[float, float]:
    ia, ib = implied(a), implied(b)
    return ia / (ia + ib), ib / (ia + ib)


def _clip(p):
    return np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)


def brier(p, y) -> float:
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def logloss(p, y) -> float:
    p, y = _clip(p), np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def calibration(p, y, bins: int = 10) -> dict:
    """Logistic recalibration y ~ a + b*logit(p) (Newton IRLS) and 10-bin ECE."""
    p, y = _clip(p), np.asarray(y, float)
    x = np.log(p / (1 - p))
    X = np.column_stack([np.ones_like(x), x])
    w = np.zeros(2)
    for _ in range(50):
        mu = 1 / (1 + np.exp(-(X @ w)))
        g = X.T @ (y - mu)
        H = (X * (mu * (1 - mu))[:, None]).T @ X
        step = np.linalg.solve(H + 1e-9 * np.eye(2), g)
        w += step
        if np.max(np.abs(step)) < 1e-10:
            break
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    ece = 0.0
    for k in range(bins):
        m = idx == k
        if m.any():
            ece += m.mean() * abs(p[m].mean() - y[m].mean())
    return {"slope": float(w[1]), "intercept": float(w[0]), "ece": float(ece)}


def market_report(rows: list[dict], *, clv_unit: str) -> dict:
    """rows: dicts with p_model, p_close (no-vig, same side/line), y (0/1, pushes
    excluded), and optional bet fields: bet_dec, bet_won (1/0/None=push), bet_ev, clv.
    """
    n = len(rows)
    if n == 0:
        return {"n": 0, "verdict": "INSUFFICIENT_DATA"}
    pm = [r["p_model"] for r in rows]
    pc = [r["p_close"] for r in rows]
    y = [r["y"] for r in rows]
    bets = [r for r in rows if r.get("bet_ev") is not None and r["bet_ev"] >= EV_THRESHOLD]
    pnl = [(r["bet_dec"] - 1.0) if r["bet_won"] == 1 else (0.0 if r["bet_won"] is None else -1.0)
           for r in bets]
    clvs = [r["clv"] for r in bets if r.get("clv") is not None]
    out = {
        "n": n,
        "brier_model": brier(pm, y), "brier_close_novig": brier(pc, y),
        "logloss_model": logloss(pm, y), "logloss_close_novig": logloss(pc, y),
        "calibration_model": calibration(pm, y),
        "calibration_close_novig": calibration(pc, y),
        "bets_ev_ge_2pct": len(bets),
        "roi_at_logged_price": (sum(pnl) / len(pnl)) if pnl else None,
        "mean_clv": (sum(clvs) / len(clvs)) if clvs else None,
        "clv_n": len(clvs), "clv_unit": clv_unit,
    }
    if n < MIN_N_FOR_VERDICT:
        out["verdict"] = "INSUFFICIENT_DATA"
    elif out["brier_model"] < out["brier_close_novig"] and out["logloss_model"] < out["logloss_close_novig"]:
        out["verdict"] = "BEATS_CLOSE"
    else:
        out["verdict"] = "LOSES_TO_CLOSE"
    return out
