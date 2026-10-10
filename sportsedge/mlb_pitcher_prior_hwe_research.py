"""Held-out check of the frozen few-starts fallback on PITCHER_HITS_WALKS_ER (H+W+ER).

Protocol: docs/MLB_PITCHER_PRIOR_FALLBACK_HWE_PREREG.md (pre-registered). Research only:
never imported by production engines, changes no model_p. The candidate is the
production #1495/#1500 fallback (league_short pool, m = 4, n = k + m) with no tuning,
applied to the per-start sum hits + walks + earned runs.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from sportsedge import mlb_pitcher_prior_ext_research as X
from sportsedge import mlb_pitcher_prior_research as R

PREREG_PATH = Path(__file__).resolve().parents[1] / "docs" / "MLB_PITCHER_PRIOR_FALLBACK_HWE_PREREG.md"
POOL = "league_short"
M = 4.0
SEED = 20261010
STAT = "hwe"
CAP = 25
THRESH = np.arange(0, CAP) + 0.5
TYPICAL = (2.5, 4.5, 6.5, 8.5, 10.5)
MARKET = "PITCHER_HITS_WALKS_ER"


class HweResearchError(ValueError):
    pass


def prereg_sha256() -> str:
    return hashlib.sha256(PREREG_PATH.read_bytes()).hexdigest()


def hwe(s: X.XStart) -> int:
    return int(s.h) + int(s.bb) + int(s.er)


def _over_frac(values: Sequence[int]) -> np.ndarray:
    return R._over_frac(R._hist(values, CAP), THRESH)


def league_short_pool(prior_season_starts: Sequence[X.XStart], window: Mapping[X.XStart, list[X.XStart]]) -> np.ndarray:
    short = [s for s in prior_season_starts if len(window.get(s, ())) < R.MIN_PRODUCTION_STARTS]
    if len(short) < 100:
        raise HweResearchError(f"league_short pool too small: {len(short)}")
    return _over_frac([hwe(s) for s in short])


def predict_own(own: Sequence[X.XStart]) -> np.ndarray:
    k = len(own)
    if k < 1:
        raise HweResearchError("own-only needs k>=1")
    return R.posterior_over(_over_frac([hwe(s) for s in own]), float(k))


def predict_fallback(own: Sequence[X.XStart], prior: np.ndarray, m: float = M) -> np.ndarray:
    """Production fallback: over = (own_over*k + prior_over*m)/(k+m), Jeffreys with n = k+m."""
    k = len(own)
    mass = prior * m if k == 0 else _over_frac([hwe(s) for s in own]) * k + prior * m
    return R.posterior_over(mass / (k + m), k + m)


def rps(p_over: np.ndarray, y: int) -> float:
    return float(((p_over - (y > THRESH).astype(float)) ** 2).sum())


def evaluate(eval_starts: Sequence[X.XStart], window: Mapping[X.XStart, list[X.XStart]], prior: np.ndarray, *, ks: Iterable[int]) -> list[dict[str, Any]]:
    ks = set(ks)
    rows = []
    for s in eval_starts:
        hist = window.get(s, [])
        if len(hist) not in ks:
            continue
        own = hist[-R.OWN_WINDOW:]
        preds = {"fallback": predict_fallback(own, prior)}
        if own:
            preds["own"] = predict_own(own)
        rows.append({"pitcher_id": s.pitcher_id, "k": len(own), "y": hwe(s), "preds": preds})
    return rows


def reference_rows(eval_starts: Sequence[X.XStart], window: Mapping[X.XStart, list[X.XStart]]) -> list[dict[str, Any]]:
    rows = []
    for s in eval_starts:
        hist = window.get(s, [])
        if len(hist) < R.MIN_PRODUCTION_STARTS:
            continue
        rows.append({"pitcher_id": s.pitcher_id, "k": len(hist), "y": hwe(s), "preds": {"own": predict_own(hist[-R.OWN_WINDOW:])}})
    return rows


def mean_rps(rows: Sequence[Mapping[str, Any]], name: str) -> float:
    vals = [rps(r["preds"][name], r["y"]) for r in rows if name in r["preds"]]
    return float(np.mean(vals)) if vals else float("nan")


def cluster_bootstrap_diff(rows: Sequence[Mapping[str, Any]], a: str, b: str, *, reps: int = 2000, seed: int = SEED) -> dict[str, float]:
    clusters: dict[int, list[float]] = {}
    for r in rows:
        if a in r["preds"] and b in r["preds"]:
            clusters.setdefault(r["pitcher_id"], []).append(rps(r["preds"][a], r["y"]) - rps(r["preds"][b], r["y"]))
    if not clusters:
        raise HweResearchError("no paired rows")
    sums = np.array([sum(v) for v in clusters.values()])
    counts = np.array([len(v) for v in clusters.values()], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(sums), size=(reps, len(sums)))
    boots = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    return {"diff": float(sums.sum() / counts.sum()), "lo": float(np.quantile(boots, 0.025)), "hi": float(np.quantile(boots, 0.975)),
            "pitchers": float(len(sums)), "starts": float(counts.sum())}


def typical_line_metrics(rows: Sequence[Mapping[str, Any]], name: str) -> dict[str, float]:
    ps, ys = [], []
    for r in rows:
        if name not in r["preds"]:
            continue
        for line in TYPICAL:
            i = int(np.where(np.isclose(THRESH, line))[0][0])
            ps.append(float(r["preds"][name][i]))
            ys.append(1.0 if r["y"] > line else 0.0)
    if not ps:
        return {"n": 0.0, "logloss": float("nan"), "ece": float("nan")}
    p = np.clip(np.array(ps), 1e-6, 1 - 1e-6)
    y = np.array(ys)
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    bins = np.minimum((p * 10).astype(int), 9)
    ece = sum(float((bins == b).mean()) * abs(float(p[bins == b].mean()) - float(y[bins == b].mean())) for b in range(10) if (bins == b).any())
    return {"n": float(len(p)), "logloss": ll, "ece": float(ece)}


def ship_decision(test_rows, consistency_rows, ref_rows) -> dict[str, Any]:
    boot = cluster_bootstrap_diff(test_rows, "fallback", "own")
    cons = cluster_bootstrap_diff(consistency_rows, "fallback", "own")
    fb = typical_line_metrics(test_rows, "fallback")
    own = typical_line_metrics(test_rows, "own")
    ref = typical_line_metrics(ref_rows, "own")
    ece_cap = max(0.03, ref["ece"] + 0.01)
    rule1 = boot["hi"] < 0
    rule2 = fb["ece"] <= ece_cap
    rule3 = cons["diff"] < 0
    return {"pool": POOL, "m": M, "market": MARKET,
            "test_vs_own": boot, "consistency_vs_own": cons, "fallback_typical": fb, "own_typical": own,
            "reference_typical": ref, "ece_cap": ece_cap,
            "rule1_beats_own_2025": rule1, "rule2_calibrated_2025": rule2, "rule3_sign_2024": rule3,
            "ships": bool(rule1 and rule2 and rule3)}
