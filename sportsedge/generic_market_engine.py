"""Generic price-independent runtime engines for the expanded MLB market surface.

Known behaviorally non-compliant markets fail closed until their replacement model
is implemented and validated. Generic analytic paths remain available only where
behavioral evidence or an explicitly isolated challenger supports them.
"""
from __future__ import annotations

import hashlib
import json
from math import comb, exp, floor, isfinite
from typing import Any, Mapping

GENERIC_ENGINE_VERSION = "mlb_full_market_runtime_v2"
PA_BOUNDED_ENGINE_VERSION = "mlb_pa_bounded_count_v1"

GAME_MARKETS = {
    "MONEYLINE", "RUN_LINE", "TOTALS", "NRFI", "YRFI",
    "F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS",
}
COUNT_MARKETS = {
    "HOME_RUNS", "RBI", "RUNS", "HITS_RUNS_RBIS", "SINGLES", "DOUBLES", "TRIPLES",
    "BATTER_BB", "BATTER_K", "STOLEN_BASES", "PITCHER_K", "PITCHER_HITS_ALLOWED",
    "PITCHER_ER", "PITCHER_OUTS",
}
PA_BOUNDED_COUNT_MARKETS = {"BATTER_K", "BATTER_BB", "SINGLES", "DOUBLES"}
BINARY_MARKETS = {"PITCHER_RECORD_WIN", "FIRST_HOME_RUN"}

FAIL_CLOSED_MARKETS = {
    "F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS",
    "PITCHER_OUTS", "HITS_RUNS_RBIS", "FIRST_HOME_RUN",
    "PITCHER_ER", "RBI", "PITCHER_RECORD_WIN",
}


class GenericMarketEngineError(ValueError):
    pass


def _canonical_json_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _finite(value: Any, name: str, *, lower: float | None = None, upper: float | None = None) -> float:
    if isinstance(value, bool):
        raise GenericMarketEngineError(f"{name} must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise GenericMarketEngineError(f"{name} must be numeric") from exc
    if not isfinite(out):
        raise GenericMarketEngineError(f"{name} must be finite")
    if lower is not None and out < lower:
        raise GenericMarketEngineError(f"{name} must be >= {lower}")
    if upper is not None and out > upper:
        raise GenericMarketEngineError(f"{name} must be <= {upper}")
    return out


def _base_output(model_input: Mapping[str, Any], model_p: float, *, model_hash: str) -> dict[str, Any]:
    return {
        "game_id": model_input.get("game_id"),
        "market": model_input.get("market"),
        "entity_id": model_input.get("entity_id"),
        "line": model_input.get("line"),
        "side": model_input.get("side"),
        "model_p": float(model_p),
        "model_input_hash": model_hash,
        "engine_version": GENERIC_ENGINE_VERSION,
        "seed_policy": "analytic_or_identity_bound",
        "mc_paths": 0,
    }


def _poisson_cdf(k: int, lam: float) -> float:
    if k < 0:
        return 0.0
    term = exp(-lam)
    total = term
    for i in range(1, k + 1):
        term *= lam / i
        total += term
    return min(1.0, max(0.0, total))


def _binomial_cdf(k: int, n: int, p: float) -> float:
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    q = 1.0 - p
    total = sum(comb(n, x) * (p ** x) * (q ** (n - x)) for x in range(k + 1))
    return min(1.0, max(0.0, total))


def _count_probability(model_input: Mapping[str, Any]) -> dict[str, Any]:
    market = str(model_input.get("market"))
    if market not in COUNT_MARKETS:
        raise GenericMarketEngineError("count adapter received non-count market")
    if market in FAIL_CLOSED_MARKETS:
        raise GenericMarketEngineError(f"{market}_BEHAVIORAL_REBUILD_REQUIRED")
    lam = _finite(model_input.get("expected_count"), "expected_count", lower=0.0)
    line = _finite(model_input.get("line"), "line", lower=0.0)
    side = str(model_input.get("side", "")).upper()
    if side not in {"OVER", "UNDER"}:
        raise GenericMarketEngineError("count market side must be OVER or UNDER")

    k_over = floor(line)
    engine_version = GENERIC_ENGINE_VERSION
    digest_fields: dict[str, Any] = {
        "market": market,
        "expected_count": lam,
        "line": line,
        "side": side,
        "game_id": model_input.get("game_id"),
        "entity_id": model_input.get("entity_id"),
        "feature_source_hash": model_input.get("feature_source_hash"),
    }

    if market in PA_BOUNDED_COUNT_MARKETS:
        projected_pa = _finite(model_input.get("projected_pa"), "projected_pa", lower=0.0)
        n = floor(projected_pa + 0.5)
        if n < 1:
            raise GenericMarketEngineError("projected_pa rounds to invalid n < 1")
        p_event = lam / n
        if p_event > 1.0:
            raise GenericMarketEngineError("expected_count/projected_pa implies p > 1")
        p_over = 1.0 - _binomial_cdf(k_over, n, p_event)
        p_under = _binomial_cdf(int(line) - 1, n, p_event) if float(line).is_integer() else 1.0 - p_over
        engine_version = PA_BOUNDED_ENGINE_VERSION
        digest_fields.update({"projected_pa": projected_pa, "n": n, "p": p_event})
    else:
        p_over = 1.0 - _poisson_cdf(k_over, lam)
        p_under = _poisson_cdf(int(line) - 1, lam) if float(line).is_integer() else 1.0 - p_over

    p = p_over if side == "OVER" else p_under
    digest_fields["engine"] = engine_version
    out = _base_output(model_input, p, model_hash=_canonical_json_sha256(digest_fields))
    out["engine_version"] = engine_version
    return out


def _binary_probability(model_input: Mapping[str, Any]) -> dict[str, Any]:
    market = str(model_input.get("market"))
    if market not in BINARY_MARKETS:
        raise GenericMarketEngineError("binary adapter received non-binary market")
    if market in FAIL_CLOSED_MARKETS:
        raise GenericMarketEngineError(f"{market}_BEHAVIORAL_REBUILD_REQUIRED")
    p_yes = _finite(model_input.get("event_probability"), "event_probability", lower=0.0, upper=1.0)
    side = str(model_input.get("side", "")).upper()
    if side not in {"YES", "NO"}:
        raise GenericMarketEngineError("binary market side must be YES or NO")
    p = p_yes if side == "YES" else 1.0 - p_yes
    digest = _canonical_json_sha256({
        "engine": GENERIC_ENGINE_VERSION,
        "market": market,
        "event_probability": p_yes,
        "side": side,
        "game_id": model_input.get("game_id"),
        "entity_id": model_input.get("entity_id"),
        "feature_source_hash": model_input.get("feature_source_hash"),
    })
    return _base_output(model_input, p, model_hash=digest)


def _game_probability(model_input: Mapping[str, Any]) -> dict[str, Any]:
    from .v7_distribution import (
        DEFAULT_EXTRA_HALF_INNING_MEAN,
        DEFAULT_FIRST_INNING_DISPERSION_R,
        DEFAULT_FIRST_INNING_SHARE,
        V7_DISTRIBUTION_VERSION,
        simulate_game_distribution,
    )

    market = str(model_input.get("market"))
    if market not in GAME_MARKETS:
        raise GenericMarketEngineError("game adapter received non-game market")
    if market in FAIL_CLOSED_MARKETS:
        raise GenericMarketEngineError(f"{market}_STATE_MODEL_REBUILD_REQUIRED")

    away_mean = _finite(model_input.get("away_mean_runs"), "away_mean_runs", lower=0.000001)
    home_mean = _finite(model_input.get("home_mean_runs"), "home_mean_runs", lower=0.000001)
    line = _finite(model_input.get("line", 0.0), "line")
    total_line = line if market == "TOTALS" else _finite(model_input.get("total_line", 0.0), "total_line", lower=0.0)
    simulations = int(model_input.get("simulations", 50000))

    game_build_hash = _canonical_json_sha256({
        "engine": V7_DISTRIBUTION_VERSION,
        "game_id": model_input.get("game_id"),
        "away_mean_runs": away_mean,
        "home_mean_runs": home_mean,
        "feature_source_hash": model_input.get("feature_source_hash"),
    })
    result = simulate_game_distribution(
        away_mean_runs=away_mean,
        home_mean_runs=home_mean,
        total_line=total_line,
        simulations=simulations,
        build_hash=game_build_hash,
        # These candidate-form parameters are intentionally locked here rather than
        # inherited from the obsolete generic feature knob. They remain unpromoted
        # until fitted/validated on the historical substrate.
        first_inning_share=DEFAULT_FIRST_INNING_SHARE,
        first_inning_dispersion_r=DEFAULT_FIRST_INNING_DISPERSION_R,
        extra_half_inning_mean=DEFAULT_EXTRA_HALF_INNING_MEAN,
    )
    side = str(model_input.get("side", "")).upper()
    if market == "MONEYLINE":
        if side in {"HOME", "HOME_ML"}:
            p = result.home_win_probability
        elif side in {"AWAY", "AWAY_ML"}:
            p = result.away_win_probability
        else:
            raise GenericMarketEngineError("moneyline side must be HOME or AWAY")
    elif market == "RUN_LINE":
        if line == -1.5 and side in {"HOME", "HOME_RL"}:
            p = result.home_minus_1_5_probability
        elif line == 1.5 and side in {"AWAY", "AWAY_RL"}:
            p = result.away_plus_1_5_probability
        else:
            raise GenericMarketEngineError("run-line adapter currently supports HOME -1.5 or AWAY +1.5")
    elif market == "TOTALS":
        if side == "OVER":
            p = result.over_probability
        elif side == "UNDER":
            p = result.under_probability
        else:
            raise GenericMarketEngineError("totals side must be OVER or UNDER")
    elif market == "NRFI":
        if side in {"YES", "NRFI"}:
            p = result.nrfi_probability
        elif side == "NO":
            p = result.yrfi_probability
        else:
            raise GenericMarketEngineError("NRFI side must be YES/NO")
    elif market == "YRFI":
        if side in {"YES", "YRFI"}:
            p = result.yrfi_probability
        elif side == "NO":
            p = result.nrfi_probability
        else:
            raise GenericMarketEngineError("YRFI side must be YES/NO")
    else:
        raise GenericMarketEngineError(f"unsupported game market {market}")
    out = _base_output(model_input, p, model_hash=result.result_sha256)
    out["mc_paths"] = result.simulations
    out["engine_version"] = V7_DISTRIBUTION_VERSION
    out["seed_policy"] = result.seed_policy
    return out


def generic_market_engine_adapter(model_input: Mapping[str, Any]) -> dict[str, Any]:
    market = str(model_input.get("market"))
    if market in GAME_MARKETS:
        return _game_probability(model_input)
    if market in COUNT_MARKETS:
        return _count_probability(model_input)
    if market in BINARY_MARKETS:
        return _binary_probability(model_input)
    raise GenericMarketEngineError(f"unsupported generic market {market}")
