"""Power ratings fitted by weighted ridge least squares.

The same solver does two jobs:
  * market ratings  -> fit to the book's own closing spreads (what the book believes)
  * results ratings -> fit to actual final margins (what happened)
Each row: (home, away, value, weight, neutral). Model: value ~ r[home] - r[away] + hfa*(not neutral).
"""
import numpy as np


def fit(rows, ridge: float = 1.0, prior: dict | None = None):
    teams = sorted({r[0] for r in rows} | {r[1] for r in rows})
    if not teams:
        return {}, 0.0
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    X = np.zeros((len(rows), n + 1))
    y = np.zeros(len(rows))
    w = np.zeros(len(rows))
    for k, (h, a, v, wt, neutral) in enumerate(rows):
        X[k, idx[h]] = 1.0
        X[k, idx[a]] = -1.0
        X[k, n] = 0.0 if neutral else 1.0
        y[k] = v
        w[k] = wt
    p = np.zeros(n + 1)
    if prior:
        for t, i in idx.items():
            p[i] = prior.get(t, 0.0)
    W = np.sqrt(w)[:, None]
    # ridge pulls ratings toward the prior (or 0); hfa is unpenalised
    R = np.sqrt(ridge) * np.eye(n + 1)
    R[n, n] = 0.0
    A = np.vstack([X * W, R])
    b = np.concatenate([y * np.sqrt(w), R @ p])
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    return {t: sol[i] for t, i in idx.items()}, float(sol[n])


def predict(r: dict, hfa: float, home: str, away: str, neutral: bool = False) -> float:
    return r.get(home, 0.0) - r.get(away, 0.0) + (0.0 if neutral else hfa)
