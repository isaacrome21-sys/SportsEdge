"""One coherent quarter-by-quarter NBA score simulation with overtime.

Research only. Every market (full game, team totals, halves, quarters, ML)
is read from the SAME simulated paths, so they are mutually consistent.
Quarter shares, per-quarter residual SDs, home/away residual correlation,
regulation share and overtime scoring are calibrated ONLY on games that
started strictly before ``as_of``. Means come from the as-of team ratings.
No odds enter; rest_adj stays 0.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from typing import Sequence

import numpy as np

VERSION = "NBA_QUARTER_JOINT_SIM_V1_20261013"


@dataclass(frozen=True)
class QuarterGame:
    game_id: str
    start: datetime
    home_lines: tuple  # per-period points: Q1..Q4 then OT periods
    away_lines: tuple


@dataclass(frozen=True)
class QuarterCalibration:
    as_of: datetime
    n_games: int
    shares: tuple       # 4 regulation quarter shares of regulation points
    resid_sd: tuple     # per-quarter team residual SD (points)
    rho: float          # home/away same-quarter residual correlation
    reg_share: float    # regulation points / final points
    ot_mean: float      # per-team points per OT period
    ot_sd: float


def calibrate(games: Sequence[QuarterGame], as_of: datetime) -> QuarterCalibration:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("AS_OF_TIMEZONE_REQUIRED")
    prior = sorted((g for g in games if g.start < as_of), key=lambda g: (g.start, g.game_id))
    prior = [g for g in prior if len(g.home_lines) >= 4 and len(g.home_lines) == len(g.away_lines)]
    if len(prior) < 30:
        raise ValueError("FEWER_THAN_30_PRIOR_QUARTER_GAMES")
    H = np.array([g.home_lines[:4] for g in prior], float)
    A = np.array([g.away_lines[:4] for g in prior], float)
    reg = np.concatenate([H, A])
    reg_tot = reg.sum(1, keepdims=True)
    shares = (reg / reg_tot).mean(0)
    shares = shares / shares.sum()
    # Residual of a quarter around the team's own season-level regulation mean
    team_mean = reg_tot.mean()
    rh = H - team_mean * shares
    ra = A - team_mean * shares
    resid_sd = tuple(float(x) for x in np.sqrt(((np.concatenate([rh, ra])) ** 2).mean(0)))
    rho = float(np.mean([np.corrcoef(rh[:, q], ra[:, q])[0, 1] for q in range(4)]))
    final = np.array([sum(g.home_lines) + sum(g.away_lines) for g in prior], float)
    reg_share = float((H.sum(1) + A.sum(1)).sum() / final.sum())
    ot = [p for g in prior for p in list(g.home_lines[4:]) + list(g.away_lines[4:])]
    ot_mean = float(np.mean(ot)) if len(ot) >= 10 else 10.0
    ot_sd = float(np.std(ot)) if len(ot) >= 10 else 4.0
    return QuarterCalibration(as_of, len(prior), tuple(float(s) for s in shares), resid_sd,
                              rho, reg_share, ot_mean, ot_sd)


def simulate(cal: QuarterCalibration, home_mean: float, away_mean: float, *,
             n: int = 4000, seed: int = 0, max_ot: int = 6):
    """Return integer path arrays: home[n, periods], away[n, periods]."""
    rng = np.random.default_rng(seed)
    hm, am = home_mean * cal.reg_share, away_mean * cal.reg_share
    H = np.zeros((n, 4 + max_ot), int)
    A = np.zeros((n, 4 + max_ot), int)
    for q in range(4):
        s = cal.resid_sd[q]
        cov = [[s * s, cal.rho * s * s], [cal.rho * s * s, s * s]]
        z = rng.multivariate_normal([hm * cal.shares[q], am * cal.shares[q]], cov, size=n)
        H[:, q] = np.maximum(0, np.rint(z[:, 0]))
        A[:, q] = np.maximum(0, np.rint(z[:, 1]))
    tied = H[:, :4].sum(1) == A[:, :4].sum(1)
    for k in range(max_ot):
        if not tied.any():
            break
        z = rng.normal(cal.ot_mean, cal.ot_sd, size=(n, 2))
        H[tied, 4 + k] = np.maximum(0, np.rint(z[tied, 0]))
        A[tied, 4 + k] = np.maximum(0, np.rint(z[tied, 1]))
        tied = tied & (H.sum(1) == A.sum(1))
    if tied.any():  # vanishingly rare; break by a final point, never leave a tie
        flip = rng.random(n) < 0.5
        H[tied & flip, -1] += 1
        A[tied & ~flip, -1] += 1
    return H, A


def settle_over(values: np.ndarray, line: float) -> dict:
    """Over/under with explicit push mass for whole-number lines."""
    over = float((values > line).mean())
    push = float((values == line).mean())
    return {"over": over, "under": 1 - over - push, "push": push}


def markets(H: np.ndarray, A: np.ndarray) -> dict:
    """Coherent readouts from one path set."""
    return {
        "home": H.sum(1), "away": A.sum(1), "total": H.sum(1) + A.sum(1),
        "margin": H.sum(1) - A.sum(1),
        "h1_total": H[:, :2].sum(1) + A[:, :2].sum(1),
        "h1_margin": H[:, :2].sum(1) - A[:, :2].sum(1),
        "q1_total": H[:, 0] + A[:, 0],
        "home_ml": float((H.sum(1) > A.sum(1)).mean()),
        "went_ot": float((H[:, 4:].sum(1) + A[:, 4:].sum(1) > 0).mean()),
    }


VERSION_V2 = "NBA_QUARTER_JOINT_SIM_V2_REGSHARE_20261013"


def simulate_v2(cal: QuarterCalibration, home_mean: float, away_mean: float, *,
                n: int = 4000, seed: int = 0, max_ot: int = 6):
    """V2 (pre-registered): one moment-matching step on regulation means.

    Simulate with V1 scaling, then shift both regulation means by the same
    additive ``d`` so the simulated expected FINAL total equals the rating
    total (margin preserved). Re-simulate with the same seed. Exactly one
    correction step; no fitted parameter.
    """
    H, A = simulate(cal, home_mean, away_mean, n=n, seed=seed, max_ot=max_ot)
    d = (home_mean + away_mean - float((H.sum(1) + A.sum(1)).mean())) / 2.0
    if cal.reg_share <= 0:
        raise ValueError("REG_SHARE_NONPOSITIVE")
    adj = d / cal.reg_share  # simulate() multiplies the passed mean by reg_share
    return simulate(cal, home_mean + adj, away_mean + adj, n=n, seed=seed, max_ot=max_ot)


VERSION_OT_FIX = "NBA_QUARTER_JOINT_SIM_OT_FIX_20261013"
OT_FIX_GRID = tuple(round(0.60 + 0.02 * i, 2) for i in range(21))


def simulate_margin_scaled(cal: QuarterCalibration, home_mean: float, away_mean: float, *,
                           c: float, n: int = 4000, seed: int = 0, max_ot: int = 6):
    """Pre-registered OT-frequency arm: shrink regulation-quarter margin
    dispersion by ``c`` about its mean, leaving each quarter's sum intact.
    Same RNG stream and OT logic as :func:`simulate`."""
    if not 0 < c <= 1.5:
        raise ValueError("MARGIN_SCALE_OUT_OF_RANGE")
    rng = np.random.default_rng(seed)
    hm, am = home_mean * cal.reg_share, away_mean * cal.reg_share
    H = np.zeros((n, 4 + max_ot), int)
    A = np.zeros((n, 4 + max_ot), int)
    for q in range(4):
        s = cal.resid_sd[q]
        cov = [[s * s, cal.rho * s * s], [cal.rho * s * s, s * s]]
        mu = [hm * cal.shares[q], am * cal.shares[q]]
        z = rng.multivariate_normal(mu, cov, size=n)
        tot = (z[:, 0] + z[:, 1]) / 2
        mar = (z[:, 0] - z[:, 1]) / 2
        mar = (mu[0] - mu[1]) / 2 + c * (mar - (mu[0] - mu[1]) / 2)
        H[:, q] = np.maximum(0, np.rint(tot + mar))
        A[:, q] = np.maximum(0, np.rint(tot - mar))
    tied = H[:, :4].sum(1) == A[:, :4].sum(1)
    for k in range(max_ot):
        if not tied.any():
            break
        z = rng.normal(cal.ot_mean, cal.ot_sd, size=(n, 2))
        H[tied, 4 + k] = np.maximum(0, np.rint(z[tied, 0]))
        A[tied, 4 + k] = np.maximum(0, np.rint(z[tied, 1]))
        tied = tied & (H.sum(1) == A.sum(1))
    if tied.any():
        flip = rng.random(n) < 0.5
        H[tied & flip, -1] += 1
        A[tied & ~flip, -1] += 1
    return H, A
