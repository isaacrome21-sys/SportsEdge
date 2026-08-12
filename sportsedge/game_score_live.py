"""Live ML/RL/TOTALS inference for the canonical GAME_SCORE_V4 artifact."""
from __future__ import annotations

import math
from typing import Any, Mapping
import numpy as np
from .game_live_features import RUN_FEATURES, verify_artifact_feature_contract

ENGINE_VERSION = "game_score_live_v1"
BANNED_FEATURE_PATTERNS = (
    "market_prob", "novig", "implied_prob", "dk_prob", "sportsbook_prob",
    "consensus_prob", "closing_prob", "american_odds", "price", "odds",
)

class GameScoreInferenceError(ValueError):
    pass

def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))

def _nb_draw(rng: np.random.Generator, mu: np.ndarray, alpha: float, n: int) -> np.ndarray:
    if alpha <= 1e-12:
        return rng.poisson(mu, size=n)
    lam = rng.gamma(shape=1 / alpha, scale=alpha * mu, size=n)
    return rng.poisson(lam)

def assert_no_sportsbook_contamination(feature_payload: Mapping[str, Any] | None) -> None:
    if feature_payload is None:
        return
    for key in feature_payload:
        low = str(key).lower()
        if any(p in low for p in BANNED_FEATURE_PATTERNS):
            raise GameScoreInferenceError(f"SPORTSBOOK_FEATURE_BANNED: {key}")

def _validate_rows(run_rows: list[list[float]]) -> np.ndarray:
    if not isinstance(run_rows, (list, tuple)) or len(run_rows) != 2:
        raise GameScoreInferenceError("RUN_ROWS_MUST_HAVE_AWAY_AND_HOME")
    for row in run_rows:
        if len(row) != len(RUN_FEATURES):
            raise GameScoreInferenceError("RUN_FEATURE_ROW_LENGTH_MISMATCH")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v) for v in row):
            raise GameScoreInferenceError("RUN_FEATURE_INVALID")
    return np.asarray(run_rows, dtype=float)

def expected_runs(artifact: Mapping[str, Any], run_rows: list[list[float]]) -> tuple[float, float]:
    verify_artifact_feature_contract(artifact, kind="run")
    X = _validate_rows(run_rows)
    raw = artifact["run_model"].predict(X)
    away = float(raw[0]) * float(artifact["away_scale"])
    home = float(raw[1]) * float(artifact["home_scale"])
    if not (math.isfinite(away) and math.isfinite(home) and away > 0 and home > 0):
        raise GameScoreInferenceError("EXPECTED_RUNS_INVALID")
    return away, home

def simulate_game(artifact: Mapping[str, Any], run_rows: list[list[float]], *, game_id: int, n_sims: int = 7000) -> dict[str, Any]:
    """Reproduce the validated v3.1 holdout simulation exactly for one game."""
    away_mu, home_mu = expected_runs(artifact, run_rows)
    alpha = float(artifact["alpha"]); sigma = float(artifact["shared_sigma"])
    rng = np.random.default_rng(99173 + int(game_id) % 100000)
    shared = rng.lognormal(-0.5 * sigma * sigma, sigma, n_sims) if sigma > 0 else np.ones(n_sims)
    away = _nb_draw(rng, away_mu * shared, alpha, n_sims)
    home = _nb_draw(rng, home_mu * shared, alpha, n_sims)
    margin = home - away; total = home + away
    raw_home_ml = float(np.mean(home > away) + 0.5 * np.mean(home == away))
    home_ml = float(artifact["ml_calibrator"].predict_proba(_logit(np.asarray([raw_home_ml])).reshape(-1, 1))[0, 1])
    return {
        "engine_version": ENGINE_VERSION, "artifact_version": artifact.get("version"),
        "game_id": int(game_id), "n_sims": int(n_sims), "away_mu": away_mu, "home_mu": home_mu,
        "home_ml_p": home_ml, "away_ml_p": 1.0 - home_ml, "margin": margin, "total_runs": total,
    }

def price_game_quote(sim: Mapping[str, Any], quote: Mapping[str, Any]) -> dict[str, Any]:
    market = str(quote.get("market") or "").upper(); side = str(quote.get("side") or "").upper()
    if market == "MONEYLINE":
        if side == "HOME": p = float(sim["home_ml_p"])
        elif side == "AWAY": p = float(sim["away_ml_p"])
        else: raise GameScoreInferenceError("MONEYLINE_SIDE_INVALID")
    elif market == "RUN_LINE":
        line = quote.get("line")
        if line is None: raise GameScoreInferenceError("RUN_LINE_MISSING")
        margin = np.asarray(sim["margin"])
        if side == "HOME": p = float(np.mean(margin + float(line) > 0))
        elif side == "AWAY": p = float(np.mean(-margin + float(line) > 0))
        else: raise GameScoreInferenceError("RUN_LINE_SIDE_INVALID")
    elif market == "TOTALS":
        line = quote.get("line")
        if line is None: raise GameScoreInferenceError("TOTAL_LINE_MISSING")
        total = np.asarray(sim["total_runs"])
        if side == "OVER": p = float(np.mean(total > float(line)))
        elif side == "UNDER": p = float(np.mean(total < float(line)))
        else: raise GameScoreInferenceError("TOTAL_SIDE_INVALID")
    else:
        raise GameScoreInferenceError(f"UNSUPPORTED_GAME_MARKET: {market}")
    return {"market": market, "side": side, "model_p": p, "engine_version": sim["engine_version"], "artifact_version": sim["artifact_version"], "n_sims": sim["n_sims"]}
