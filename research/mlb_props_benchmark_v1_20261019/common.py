"""Shared helpers for the backtest sweep. Same bootstrap as the frozen ev.py (seed 20261017, 2000 cluster resamples)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

SWEEP = Path(__file__).resolve().parent
SCRATCH = SWEEP.parent
SEED, RESAMPLES = 20261017, 2000
MIN_BETS = 200          # below this, the row is INSUFFICIENT_DATA regardless of CI
MIN_CLUSTERS = 10       # below this many date/event clusters, INSUFFICIENT_DATA


def boot(vals, clusters):
    """Cluster bootstrap of the mean (ratio of cluster sums), same estimator as ev.boot."""
    vals = np.asarray(vals, float)
    clusters = list(clusters)
    if len(vals) == 0:
        return {"mean": None, "lo": None, "hi": None, "n": 0, "n_clusters": 0}
    keys = sorted(set(clusters))
    idx = {k: i for i, k in enumerate(keys)}
    bi = np.array([idx[c] for c in clusters])
    sums, cnts = np.zeros(len(keys)), np.zeros(len(keys))
    np.add.at(sums, bi, vals)
    np.add.at(cnts, bi, 1)
    rng = np.random.default_rng(SEED)
    s = rng.integers(0, len(keys), size=(RESAMPLES, len(keys)))
    m = sums[s].sum(1) / cnts[s].sum(1)
    lo, hi = np.percentile(m, [2.5, 97.5])
    return {"mean": float(vals.mean()), "lo": float(lo), "hi": float(hi),
            "n": int(len(vals)), "n_clusters": int(len(keys))}


def dec_from_american(a):
    a = np.asarray(a, float)
    return np.where(a > 0, 1 + a / 100.0, 1 + 100.0 / -a)


def implied_from_american(a):
    a = np.asarray(a, float)
    return np.where(a > 0, 100.0 / (a + 100.0), -a / (-a + 100.0))


def devig_two_way(pa, pb):
    """No-vig probability of side A given the two raw implied probabilities."""
    return pa / (pa + pb)


def pnl_flat(win, push, dec_price):
    """Flat 1-unit P&L per bet: win -> dec-1, loss -> -1, push -> 0."""
    win = np.asarray(win, bool)
    push = np.asarray(push, bool)
    out = np.where(win, np.asarray(dec_price, float) - 1.0, -1.0)
    return np.where(push, 0.0, out)


def verdict(n_bets, date_ci, season_ci=None, claimed_direction="model"):
    """Model-vs-market verdict on flat-bet ROI. An edge is claimed only if the CI (against the quoted market price) excludes 0 from below.

    Interval used = the wider of the date-clustered CI and the season-clustered CI (season CI only if >= 5 seasons).
    """
    if n_bets is None or n_bets < MIN_BETS or date_ci is None or date_ci["n_clusters"] < MIN_CLUSTERS:
        return "INSUFFICIENT_DATA"
    lo, hi = date_ci["lo"], date_ci["hi"]
    if season_ci is not None and season_ci["n_clusters"] >= 5:
        lo, hi = min(lo, season_ci["lo"]), max(hi, season_ci["hi"])
    if lo > 0:
        return "BEATS_MARKET_CI_EXCLUDES_0"
    return "NO_EDGE"


def fmt_ci(c):
    if c is None or c.get("mean") is None:
        return "-"
    return f"{c['mean']*100:+.1f}% [{c['lo']*100:+.1f}, {c['hi']*100:+.1f}]"


ROWS_PATH = SWEEP / "rows.jsonl"


def record(row: dict):
    """Append one result row to rows.jsonl (idempotent per id: replaces the old row with the same id)."""
    rows = []
    if ROWS_PATH.exists():
        rows = [json.loads(l) for l in ROWS_PATH.read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r.get("id") != row["id"]]
    rows.append(row)
    ROWS_PATH.write_text("\n".join(json.dumps(r, default=float) for r in rows) + "\n")
