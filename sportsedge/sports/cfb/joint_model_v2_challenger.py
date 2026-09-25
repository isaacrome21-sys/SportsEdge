"""CFB joint score model -- V2 dispersion challenger (CANDIDATE ONLY).

Status: research challenger. Not wired into run_machine, auto_slate, the RUN IT
card, or any promotion path. Produces no Model_P, inherits no V1 evidence, and
consumes no CFB_CANDIDATE_PREREG_FREEZE_V1 attempt. It exists so the fixes below
can be measured against V1 on market-blind outcome calibration before anyone
decides whether to preregister it.

It reuses the V1 feature contract and V1 mean model unchanged (same
``_feature_vector``, same ridge coefficients). Only the score *dispersion* changes:

1. Honest residuals. V1 samples in-sample training residuals, which are shrunk
   by the fit itself. V2 uses forward-chained out-of-season residuals: season s
   residuals come from a model fit only on seasons < s. The earliest season
   contributes no residuals. Nothing from season s or later ever informs the
   spread of season s.

2. Mean-dependent spread. V1 applies the same residual cloud to a 38-point
   total and a 75-point total. CFB scoring variance grows with expected points,
   so V1 is too wide on low totals and too narrow on high totals / big spreads,
   exactly where apparent edges show up. V2 fits a per-side linear scale
   s(mu) = c0 + c1*mu on |residual|, standardizes each residual pair by the
   scale at its own game's mean, and rescales by s(mu_new) at simulation time.
   Home/away residuals stay paired, so score correlation is preserved.

3. Outcome-only calibration diagnostics (no closing lines needed): PIT/interval
   coverage of held-out margins and totals, plus key-number mass readouts for the
   frozen +-3/+-7 tolerance check.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .joint_model import (
    CFBJointScoreModel,
    CFBModelError,
    _num,
    fit_cfb_joint_score_model,
)

CFB_V2_CHALLENGER_ID = "cfb_joint_hetero_oof_v2_challenger"
CFB_V2_STATUS = "CANDIDATE_CHALLENGER_NO_MODEL_P"
CFB_V2_RESIDUAL_MODE = "FORWARD_CHAINED_OUT_OF_SEASON"
MIN_OOF_RESIDUAL_PAIRS = 100
SCALE_FLOOR_FRACTION = 0.25  # s(mu) never drops below 25% of median |residual|
KEY_MARGINS = (3, 7, 10, 14)


class CFBChallengerError(ValueError):
    pass


@dataclass(frozen=True)
class CFBScaleFit:
    intercept: float
    slope: float
    floor: float

    def at(self, mu: np.ndarray | float) -> np.ndarray:
        return np.maximum(self.floor, self.intercept + self.slope * np.asarray(mu, dtype=float))


def _fit_scale(mu: np.ndarray, resid: np.ndarray) -> CFBScaleFit:
    abs_r = np.abs(resid)
    x = np.column_stack((np.ones_like(mu), mu))
    coef, *_ = np.linalg.lstsq(x, abs_r, rcond=None)
    floor = float(SCALE_FLOOR_FRACTION * np.median(abs_r))
    if not isfinite(floor) or floor <= 0:
        raise CFBChallengerError("CFB_V2_SCALE_FLOOR_INVALID")
    return CFBScaleFit(intercept=float(coef[0]), slope=float(coef[1]), floor=floor)


@dataclass(frozen=True)
class CFBJointChallengerModel:
    challenger_id: str
    status: str
    residual_mode: str
    base: CFBJointScoreModel
    home_scale: CFBScaleFit
    away_scale: CFBScaleFit
    standardized_pairs: tuple[tuple[float, float], ...]
    residual_seasons: tuple[int, ...]

    def predict_means(self, row: Mapping[str, Any]) -> tuple[float, float]:
        return self.base.predict_means(row)

    def artifact_sha256(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        return sha256(raw).hexdigest()


def _season(row: Mapping[str, Any]) -> int:
    try:
        return int(row["season"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CFBChallengerError("CFB_V2_ROW_SEASON_REQUIRED") from exc


def fit_cfb_v2_challenger(
    rows: Iterable[Mapping[str, Any]], *, ridge_alpha: float = 10.0,
) -> CFBJointChallengerModel:
    data = [dict(r) for r in rows]
    seasons = sorted({_season(r) for r in data})
    if len(seasons) < 2:
        raise CFBChallengerError("CFB_V2_TWO_SEASONS_REQUIRED_FOR_OOF_RESIDUALS")

    base = fit_cfb_joint_score_model(data, ridge_alpha=ridge_alpha)

    mus_h: list[float] = []; mus_a: list[float] = []
    res_h: list[float] = []; res_a: list[float] = []
    used: list[int] = []
    for s in seasons[1:]:
        train = [r for r in data if _season(r) < s]
        test = [r for r in data if _season(r) == s]
        if len(train) < 20 or not test:
            continue
        fold = fit_cfb_joint_score_model(train, ridge_alpha=ridge_alpha)
        for r in test:
            mh, ma = fold.predict_means(r)
            mus_h.append(mh); mus_a.append(ma)
            res_h.append(_num(r.get("home_score"), "home_score") - mh)
            res_a.append(_num(r.get("away_score"), "away_score") - ma)
        used.append(s)
    if len(res_h) < MIN_OOF_RESIDUAL_PAIRS:
        raise CFBChallengerError(f"CFB_V2_OOF_RESIDUALS_INSUFFICIENT:{len(res_h)}")

    mh_arr, ma_arr = np.asarray(mus_h), np.asarray(mus_a)
    rh_arr, ra_arr = np.asarray(res_h), np.asarray(res_a)
    hs, as_ = _fit_scale(mh_arr, rh_arr), _fit_scale(ma_arr, ra_arr)
    zh, za = rh_arr / hs.at(mh_arr), ra_arr / as_.at(ma_arr)
    if not (np.all(np.isfinite(zh)) and np.all(np.isfinite(za))):
        raise CFBChallengerError("CFB_V2_STANDARDIZED_RESIDUAL_NONFINITE")
    return CFBJointChallengerModel(
        challenger_id=CFB_V2_CHALLENGER_ID, status=CFB_V2_STATUS, residual_mode=CFB_V2_RESIDUAL_MODE,
        base=base, home_scale=hs, away_scale=as_,
        standardized_pairs=tuple((float(a), float(b)) for a, b in zip(zh.tolist(), za.tolist())),
        residual_seasons=tuple(used),
    )


def simulate_cfb_v2_paths(
    model: CFBJointChallengerModel, row: Mapping[str, Any], *, seed: int, n_paths: int = 20000,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (home_scores, away_scores) int arrays. Ties resolved with V1's empirical OT profile."""
    if model.challenger_id != CFB_V2_CHALLENGER_ID:
        raise CFBChallengerError("CFB_V2_IDENTITY_INVALID")
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
        raise CFBChallengerError("CFB_V2_EXPLICIT_INTEGER_SEED_REQUIRED")
    if isinstance(n_paths, bool) or not isinstance(n_paths, int) or n_paths <= 0:
        raise CFBChallengerError("CFB_V2_N_PATHS_INVALID")
    mh, ma = model.predict_means(row)
    pairs = np.asarray(model.standardized_pairs, dtype=float)
    rng = np.random.default_rng(int(seed))
    idx = rng.integers(0, len(pairs), size=n_paths)
    h = np.maximum(0, np.rint(mh + pairs[idx, 0] * model.home_scale.at(mh))).astype(int)
    a = np.maximum(0, np.rint(ma + pairs[idx, 1] * model.away_scale.at(ma))).astype(int)
    ties = np.flatnonzero(h == a)
    if ties.size:
        ot = np.asarray(model.base.overtime_deltas, dtype=int)
        if ot.size == 0:
            raise CFBChallengerError("CFB_V2_OVERTIME_PROFILE_REQUIRED_FOR_TIED_PATH")
        pick = rng.integers(0, len(ot), size=ties.size)
        h[ties] += ot[pick, 0]
        a[ties] += ot[pick, 1]
        if np.any(h == a):
            raise CFBChallengerError("CFB_V2_OVERTIME_PROFILE_DID_NOT_RESOLVE_TIE")
    return h, a


def price_paths(home: np.ndarray, away: np.ndarray, *, spread_line: float, total_line: float) -> dict[str, Any]:
    """Vectorized equivalent of V1 price_cfb_game_markets (same keys, same push handling)."""
    s, t = _num(spread_line, "spread_line"), _num(total_line, "total_line")
    m, tot = home - away, home + away
    return {
        "moneyline": {"home": float(np.mean(m > 0)), "away": float(np.mean(m < 0)), "tie_unresolved": float(np.mean(m == 0))},
        "spread": {"home": float(np.mean(m + s > 0)), "away": float(np.mean(m + s < 0)), "push": float(np.mean(m + s == 0)), "home_line": s},
        "total": {"over": float(np.mean(tot > t)), "under": float(np.mean(tot < t)), "push": float(np.mean(tot == t)), "line": t},
    }


def key_number_mass(home: np.ndarray, away: np.ndarray) -> dict[int, float]:
    """P(|margin| == k) for the frozen key-number tolerance check."""
    m = np.abs(home - away)
    return {k: float(np.mean(m == k)) for k in KEY_MARGINS}


def _randomized_pit(sim: np.ndarray, actual: float, u: float) -> float:
    below, equal = np.mean(sim < actual), np.mean(sim == actual)
    return float(below + u * equal)


def outcome_calibration(
    simulate, rows: Sequence[Mapping[str, Any]], *, seed: int = 20260925, n_paths: int = 5000,
) -> dict[str, Any]:
    """Market-blind distribution calibration on held-out games.

    ``simulate(row, seed)`` must return (home, away) arrays. Returns randomized-PIT
    interval coverage for margin and total. A calibrated model hits ~0.50/0.80/0.95;
    coverage below target = distribution too narrow (overconfident edges).
    """
    rng = np.random.default_rng(seed)
    pits = {"margin": [], "total": []}
    for i, r in enumerate(rows):
        h, a = simulate(r, seed + i)
        ah, aa = _num(r.get("home_score"), "home_score"), _num(r.get("away_score"), "away_score")
        pits["margin"].append(_randomized_pit(h - a, ah - aa, rng.random()))
        pits["total"].append(_randomized_pit(h + a, ah + aa, rng.random()))
    out: dict[str, Any] = {"n": len(rows)}
    for key, vals in pits.items():
        p = np.asarray(vals)
        out[key] = {
            f"cover_{int(c * 100)}": float(np.mean(np.abs(p - 0.5) <= c / 2)) for c in (0.5, 0.8, 0.95)
        }
    return out


def simulate_v1_paths(model: CFBJointScoreModel, row: Mapping[str, Any], *, seed: int, n_paths: int = 5000):
    """Adapter so V1 can run through the same diagnostics (reads V1's own residuals)."""
    from .joint_model import simulate_cfb_joint_distribution
    d = simulate_cfb_joint_distribution(model, row, seed=seed, n_paths=n_paths)
    return np.asarray([x["home_score"] for x in d]), np.asarray([x["away_score"] for x in d])


__all__ = [
    "CFB_V2_CHALLENGER_ID", "CFB_V2_STATUS", "CFBChallengerError", "CFBJointChallengerModel",
    "fit_cfb_v2_challenger", "simulate_cfb_v2_paths", "price_paths", "key_number_mass",
    "outcome_calibration", "simulate_v1_paths",
]
