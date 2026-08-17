"""Canonical runtime engine adapters.

Adapters translate the external canonical market contract into each validated
engine's frozen input contract, then back to the common orchestrator schema.
They never read sportsbook prices or infer missing candidate identity.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Callable, Mapping

from .bb_engine import simulate_bb
from .generic_market_engine import (
    BINARY_MARKETS,
    COUNT_MARKETS,
    GAME_MARKETS,
    generic_market_engine_adapter,
)
from .hits_engine import simulate_hits
from .home_runs_engine import simulate_home_runs
from .total_bases_engine import simulate_total_bases


class EngineDispatchError(ValueError):
    pass


_HITTER_LINES = (0.5, 1.5, 2.5)
_BB_LINES = (0.5, 1.5, 2.5, 3.5)

MANUAL_MARKET_TYPE_TO_ENGINE_MARKET = {
    "MONEYLINE": "MONEYLINE",
    "GAME_TOTAL": "TOTALS",
    "RUN_LINE": "RUN_LINE",
    "FIRST_FIVE_MONEYLINE": "F5_MONEYLINE",
    "FIRST_FIVE_RUN_LINE": "F5_RUN_LINE",
    "FIRST_FIVE_TOTAL": "F5_TOTALS",
    "FIRST_INNING_TOTAL": "YRFI",
    "PITCHER_STRIKEOUTS": "PITCHER_K",
    "PITCHER_OUTS": "PITCHER_OUTS",
    "PITCHER_HITS_ALLOWED": "PITCHER_HITS_ALLOWED",
    "PITCHER_EARNED_RUNS": "PITCHER_ER",
    "PITCHER_WALKS": "PITCHER_BB",
    "BATTER_HOME_RUNS": "HOME_RUNS",
    "BATTER_HITS": "HITS",
    "BATTER_TOTAL_BASES": "TOTAL_BASES",
}


def resolve_manual_market_type(market_type: str) -> str:
    key = str(market_type or "").strip().upper()
    market = MANUAL_MARKET_TYPE_TO_ENGINE_MARKET.get(key)
    if market is None or market not in engine_registry():
        raise EngineDispatchError(f"NO_ENGINE_FOR_MARKET: {key}")
    return market


def _finite_line(value: Any) -> float:
    if isinstance(value, bool):
        raise EngineDispatchError("line must be numeric, not boolean")
    try:
        line = float(value)
    except (TypeError, ValueError) as exc:
        raise EngineDispatchError("line must be numeric") from exc
    if not isfinite(line):
        raise EngineDispatchError("line must be finite")
    return line


def _common_output(model_input: Mapping[str, Any], result, model_p: float, market: str) -> dict[str, Any]:
    return {
        "game_id": model_input.get("game_id"),
        "market": market,
        "entity_id": model_input.get("entity_id"),
        "line": model_input.get("line"),
        "side": model_input.get("side"),
        "model_p": float(model_p),
        "model_input_hash": result.model_input_hash,
        "engine_version": result.engine_version,
        "seed_policy": result.seed_policy,
        "mc_paths": result.mc_paths,
    }


def hits_engine_adapter(model_input: Mapping[str, Any]) -> dict[str, Any]:
    if model_input.get("market") != "HITS":
        raise EngineDispatchError("Hits adapter requires market=HITS")
    line = _finite_line(model_input.get("line"))
    if line not in _HITTER_LINES:
        raise EngineDispatchError(f"unsupported HITS line {line}; allowed={_HITTER_LINES}")
    side = model_input.get("side")
    if side not in ("OVER", "UNDER"):
        raise EngineDispatchError("HITS side must be OVER or UNDER")
    internal = dict(model_input); internal["market"] = "hits"
    result = simulate_hits(internal, thresholds=(line,))
    p_over = float(result.probs[line])
    return _common_output(model_input, result, p_over if side == "OVER" else 1.0 - p_over, "HITS")


def total_bases_engine_adapter(model_input: Mapping[str, Any]) -> dict[str, Any]:
    if model_input.get("market") != "TOTAL_BASES":
        raise EngineDispatchError("Total Bases adapter requires market=TOTAL_BASES")
    line = _finite_line(model_input.get("line"))
    if line not in _HITTER_LINES:
        raise EngineDispatchError(f"unsupported TOTAL_BASES line {line}; allowed={_HITTER_LINES}")
    side = model_input.get("side")
    if side not in ("OVER", "UNDER"):
        raise EngineDispatchError("TOTAL_BASES side must be OVER or UNDER")
    internal = dict(model_input); internal["market"] = "total_bases"
    result = simulate_total_bases(internal, thresholds=(line,))
    p_over = float(result.probs[line])
    return _common_output(model_input, result, p_over if side == "OVER" else 1.0 - p_over, "TOTAL_BASES")


def home_runs_engine_adapter(model_input: Mapping[str, Any]) -> dict[str, Any]:
    if model_input.get("market") != "HOME_RUNS":
        raise EngineDispatchError("Home Runs adapter requires market=HOME_RUNS")
    line = _finite_line(model_input.get("line"))
    if line != 0.5:
        raise EngineDispatchError("HOME_RUNS currently supports line=0.5 only")
    side = model_input.get("side")
    if side not in ("OVER", "UNDER"):
        raise EngineDispatchError("HOME_RUNS side must be OVER or UNDER")
    internal = dict(model_input); internal["market"] = "home_runs"
    result = simulate_home_runs(internal, thresholds=(line,))
    p_over = float(result.probs[line])
    return _common_output(model_input, result, p_over if side == "OVER" else 1.0 - p_over, "HOME_RUNS")


def pitcher_bb_engine_adapter(model_input: Mapping[str, Any]) -> dict[str, Any]:
    if model_input.get("market") != "PITCHER_BB":
        raise EngineDispatchError("Pitcher BB adapter requires market=PITCHER_BB")
    line = _finite_line(model_input.get("line"))
    if line not in _BB_LINES:
        raise EngineDispatchError(f"unsupported PITCHER_BB line {line}; allowed={_BB_LINES}")
    side = model_input.get("side")
    if side not in ("OVER", "UNDER"):
        raise EngineDispatchError("Pitcher BB side must be OVER or UNDER")
    internal = dict(model_input); internal["market"] = "pitcher_walks"
    result = simulate_bb(internal, thresholds=(line,))
    p_over = float(result.probs[line])
    return _common_output(model_input, result, p_over if side == "OVER" else 1.0 - p_over, "PITCHER_BB")


def engine_registry() -> dict[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]]:
    registry: dict[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]] = {
        "HITS": hits_engine_adapter,
        "TOTAL_BASES": total_bases_engine_adapter,
        "HOME_RUNS": home_runs_engine_adapter,
        "PITCHER_BB": pitcher_bb_engine_adapter,
    }
    for market in sorted(GAME_MARKETS | COUNT_MARKETS | BINARY_MARKETS):
        if market not in registry:
            registry[market] = generic_market_engine_adapter
    return registry
