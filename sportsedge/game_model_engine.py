"""Frozen SportsEdge MLB game-market inference core recovered from Beta v1.4.

This module contains only sportsbook-independent Model_P math. It deliberately
accepts already-built model features; sportsbook prices are not accepted as
features and cannot influence inference. Deployment eligibility remains external
and must be earned by parity/calibration evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite
from typing import Any, Mapping

import numpy as np

ENGINE_VERSION = "game_model_engine_beta_v1_4_port"
ML_FEATURE_CONTRACT_VERSION = "beta_ml_features_v1"
RUN_DISTRIBUTION_VERSION = "correlated_nb_run_split_v1"

BETA_COEFS = {
    "intercept": 0.19512015,
    "starter_fip_edge_home": -0.01025177,
    "kbb_edge_home": 1.40900700,
    "lineup_woba_edge_home": 3.86646739,
    "opp_pct_edge_home": 0.07844380,
    "switch_pct_edge_home": -0.63527626,
}
REQUIRED_ML_FEATURES = tuple(k for k in BETA_COEFS if k != "intercept")
BANNED_FEATURE_PATTERNS = (
    "market_prob", "novig", "implied_prob", "dk_prob", "sportsbook_prob",
    "consensus_prob", "closing_prob", "moneyline_odds", "american_odds",
)


class GameModelError(ValueError):
    pass


@dataclass(frozen=True)
class GameModelOutput:
    engine_version: str
    feature_contract_version: str
    run_distribution_version: str
    home_ml_anchor_p: float
    home_ml_mc_p: float
    mu_home: float
    mu_away: float
    probabilities: dict[str, float]


def _finite(name: str, value: Any, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(value, bool):
        raise GameModelError(f"invalid {name}")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise GameModelError(f"invalid {name}") from exc
    if not isfinite(out) or (lo is not None and out < lo) or (hi is not None and out > hi):
        raise GameModelError(f"invalid {name}")
    return out


def beta_ml_home_p(features: Mapping[str, Any]) -> float:
    if not isinstance(features, Mapping):
        raise GameModelError("ml_features must be an object")
    for key in features:
        low = str(key).lower()
        if any(x in low for x in BANNED_FEATURE_PATTERNS):
            raise GameModelError(f"sportsbook probability/price feature banned: {key}")
    if set(features) != set(REQUIRED_ML_FEATURES):
        missing = sorted(set(REQUIRED_ML_FEATURES) - set(features))
        extra = sorted(set(features) - set(REQUIRED_ML_FEATURES))
        raise GameModelError(f"ML_FEATURE_CONTRACT_MISMATCH missing={missing} extra={extra}")
    z = BETA_COEFS["intercept"]
    for key in REQUIRED_ML_FEATURES:
        z += BETA_COEFS[key] * _finite(key, features[key])
    return 1.0 / (1.0 + exp(-z))


def _nb_shape(mu: float, vmr: float) -> float:
    if vmr <= 1.0:
        return 1e9
    return max(mu / (vmr - 1.0), 1e-6)


def simulate_runs(*, mu_away: float, mu_home: float, vmr: float, shared_sigma: float, seed: int, n_sim: int) -> dict[str, np.ndarray]:
    mu_away = _finite("mu_away", mu_away, 1e-9)
    mu_home = _finite("mu_home", mu_home, 1e-9)
    vmr = _finite("dispersion_vmr", vmr, 1.0)
    shared_sigma = _finite("shared_sigma", shared_sigma, 0.0)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise GameModelError("seed must be integer")
    if isinstance(n_sim, bool) or not isinstance(n_sim, int) or n_sim <= 0:
        raise GameModelError("n_sim must be positive integer")
    rng = np.random.default_rng(seed)
    if shared_sigma > 0:
        shared = rng.lognormal(mean=-0.5 * shared_sigma * shared_sigma, sigma=shared_sigma, size=n_sim)
    else:
        shared = np.ones(n_sim)

    def draw_team(mu: float) -> np.ndarray:
        r = _nb_shape(mu, vmr)
        team_mult = rng.gamma(shape=r, scale=1.0 / r, size=n_sim)
        return rng.poisson(mu * shared * team_mult)

    away = draw_team(mu_away)
    home = draw_team(mu_home)
    return {"away": away, "home": home, "total": away + home, "margin_home": home - away}


def calibrate_run_split(*, target_home_p: float, total_mu: float, vmr: float = 2.226, shared_sigma: float = 0.0, seed: int = 91026, search_sims: int = 7000, final_sims: int = 50000) -> tuple[float, float, dict[str, np.ndarray], float]:
    target_home_p = _finite("target_home_p", target_home_p, 0.0500000001, 0.9499999999)
    total_mu = _finite("total_mu", total_mu, 3.000000001)
    lo, hi = 0.25, 0.75
    for i in range(18):
        share = (lo + hi) / 2.0
        mu_h = total_mu * share
        mu_a = total_mu - mu_h
        paths = simulate_runs(mu_away=mu_a, mu_home=mu_h, vmr=vmr, shared_sigma=shared_sigma, seed=seed + i, n_sim=search_sims)
        home, away = paths["home"], paths["away"]
        p_home = float(np.mean(home > away) + 0.5 * np.mean(home == away))
        if p_home < target_home_p:
            lo = share
        else:
            hi = share
    share = (lo + hi) / 2.0
    mu_h, mu_a = total_mu * share, total_mu * (1.0 - share)
    paths = simulate_runs(mu_away=mu_a, mu_home=mu_h, vmr=vmr, shared_sigma=shared_sigma, seed=seed + 1000, n_sim=final_sims)
    home, away = paths["home"], paths["away"]
    p_home = float(np.mean(home > away) + 0.5 * np.mean(home == away))
    return mu_h, mu_a, paths, p_home


def price_game_markets(*, ml_features: Mapping[str, Any], total_mu: float, lines: list[Mapping[str, Any]], vmr: float = 2.226, shared_sigma: float = 0.0, seed: int = 91026, search_sims: int = 7000, final_sims: int = 50000) -> GameModelOutput:
    anchor = beta_ml_home_p(ml_features)
    mu_home, mu_away, paths, mc_home = calibrate_run_split(target_home_p=anchor, total_mu=total_mu, vmr=vmr, shared_sigma=shared_sigma, seed=seed, search_sims=search_sims, final_sims=final_sims)
    total, margin = paths["total"], paths["margin_home"]
    probs: dict[str, float] = {}
    for row in lines:
        if not isinstance(row, Mapping):
            raise GameModelError("line request must be object")
        market = str(row.get("market") or "").upper()
        side = str(row.get("side") or "").upper()
        line = row.get("line")
        key = str(row.get("key") or f"{market}:{side}:{line}")
        if market == "MONEYLINE":
            if side == "HOME": p = mc_home
            elif side == "AWAY": p = 1.0 - mc_home
            else: raise GameModelError("MONEYLINE side must be HOME/AWAY")
        elif market == "RUN_LINE":
            ln = _finite("run_line", line)
            x = margin + ln if side == "HOME" else -margin + ln if side == "AWAY" else None
            if x is None: raise GameModelError("RUN_LINE side must be HOME/AWAY")
            p = float(np.mean(x > 0)); probs[key + ":push"] = float(np.mean(x == 0))
        elif market == "TOTALS":
            ln = _finite("total_line", line)
            if side == "OVER": p = float(np.mean(total > ln))
            elif side == "UNDER": p = float(np.mean(total < ln))
            else: raise GameModelError("TOTALS side must be OVER/UNDER")
            probs[key + ":push"] = float(np.mean(total == ln))
        else:
            raise GameModelError(f"unsupported game market: {market}")
        probs[key] = p
    return GameModelOutput(ENGINE_VERSION, ML_FEATURE_CONTRACT_VERSION, RUN_DISTRIBUTION_VERSION, anchor, mc_home, mu_home, mu_away, probs)
