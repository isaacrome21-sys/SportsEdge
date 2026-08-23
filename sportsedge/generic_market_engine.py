"""Generic price-independent runtime engines for the expanded MLB market surface.

This module does not consume sportsbook probabilities or prices. Game markets are
resolved from the shared V7 run distribution. Count props are resolved analytically
from explicit model-derived inputs. Binary props require an explicit model-derived
event_probability. Missing model features fail closed.
"""
from __future__ import annotations

import hashlib
import json
from math import comb, exp, floor, isfinite
from typing import Any, Mapping

GENERIC_ENGINE_VERSION = "mlb_full_market_runtime_v1"
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
        "seed_policy": "identity-bound-v7-or-analytic",
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
    total = 0.0
    q = 1.0 - p
    for x in range(0, k + 1):
        total += comb(n, x) * (p ** x) * (q ** (n - x))
    return min(1.0, max(0.0, total))


def _count_probability(model_input: Mapping[str, Any]) -> dict[str, Any]:
    market = str(model_input.get("market"))
    if market not in COUNT_MARKETS:
        raise GenericMarketEngineError("count adapter received non-count market")
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
        if float(line).is_integer():
            p_under = _binomial_cdf(int(line) - 1, n, p_event)
        else:
            p_under = 1.0 - p_over
        engine_version = PA_BOUNDED_ENGINE_VERSION
        digest_fields.update({"projected_pa": projected_pa, "n": n, "p": p_event})
    else:
        p_over = 1.0 - _poisson_cdf(k_over, lam)
        if float(line).is_integer():
            p_under = _poisson_cdf(int(line) - 1, lam)
        else:
            p_under = 1.0 - p_over

    p = p_over if side == "OVER" else p_under
    digest_fields["engine"] = engine_version
    digest = _canonical_json_sha256(digest_fields)
    out = _base_output(model_input, p, model_hash=digest)
    out["engine_version"] = engine_version
    return out


def _binary_probability(model_input: Mapping[str, Any]) -> dict[str, Any]:
    market = str(model_input.get("market"))
    if market not in BINARY_MARKETS:
        raise GenericMarketEngineError("binary adapter received non-binary market")
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
    })
    return _base_output(model_input, p, model_hash=digest)


def _game_probability(model_input: Mapping[str, Any]) -> dict[str, Any]:
    from .v7_distribution import simulate_game_distribution

    market = str(model_input.get("market"))
    if market not in GAME_MARKETS:
        raise GenericMarketEngineError("game adapter received non-game market")
    is_f5 = market.startswith("F5_")
    away_key = "f5_away_mean_runs" if is_f5 else "away_mean_runs"
    home_key = "f5_home_mean_runs" if is_f5 else "home_mean_runs"
    away_mean = _finite(model_input.get(away_key), away_key, lower=0.000001)
    home_mean = _finite(model_input.get(home_key), home_key, lower=0.000001)
    line = _finite(model_input.get("line", 0.0), "line")
    total_line = line if market in {"TOTALS", "F5_TOTALS"} else _finite(model_input.get("total_line", 0.0), "total_line", lower=0.0)
    seed = int(model_input.get("seed", 7))
    simulations = int(model_input.get("simulations", 50000))
    result = simulate_game_distribution(
        away_mean_runs=away_mean,
        home_mean_runs=home_mean,
        total_line=total_line,
        simulations=simulations,
        seed=seed,
        first_inning_share=model_input.get("first_inning_share", 1.0 / 9.0),
    )
    side = str(model_input.get("side", "")).upper()
    if market in {"MONEYLINE", "F5_MONEYLINE"}:
        if side in {"HOME", "HOME_ML"}:
            p = result.home_win_probability
        elif side in {"AWAY", "AWAY_ML"}:
            p = result.away_win_probability
        else:
            raise GenericMarketEngineError("moneyline side must be HOME or AWAY")
    elif market in {"RUN_LINE", "F5_RUN_LINE"}:
        if line == -1.5 and side in {"HOME", "HOME_RL"}:
            p = result.home_minus_1_5_probability
        elif line == 1.5 and side in {"AWAY", "AWAY_RL"}:
            p = result.away_plus_1_5_probability
        else:
            raise GenericMarketEngineError("run-line adapter currently supports HOME -1.5 or AWAY +1.5")
    elif market in {"TOTALS", "F5_TOTALS"}:
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
    out["engine_version"] = "mlb_v7_distribution_v1"
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
