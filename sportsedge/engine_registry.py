"""Canonical MLB runtime engine registry with migration-safe compatibility.

New manual/hybrid/automatic paths route coherent prop surfaces through shared joint
engines. Legacy HITS, TOTAL_BASES, and PITCHER_BB feature contracts remain accepted
by compatibility adapters so older callers fail neither silently nor open. HOME_RUNS
stays on its behaviorally measured generic baseline until the joint HR candidate earns
its own line-level evidence.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Callable, Mapping

from .bb_engine import simulate_bb
from .generic_market_engine import BINARY_MARKETS, GAME_MARKETS, generic_market_engine_adapter
from .hits_engine import simulate_hits
from .hitter_joint_engine import HITTER_MARKETS, price_hitter_market
from .pitcher_joint_engine import PITCHER_MARKETS, price_pitcher_market
from .shared_f5_engine import STAGE1_F5_MARKETS, build_shared_f5_engine_session
from .shared_game_engine import STAGE1_GAME_MARKETS, build_shared_game_engine_session
from .total_bases_engine import simulate_total_bases


class EngineDispatchError(ValueError):
    pass


_HITTER_LINES = (0.5, 1.5, 2.5)
_BB_LINES = (0.5, 1.5, 2.5, 3.5)
_HITS_LEGACY_KEYS = frozenset({"b_rate", "p_rate", "pa_pool"})
_TOTAL_BASES_LEGACY_KEYS = frozenset({"rates", "p_h", "p_hr", "park", "pa_pool"})
_PITCHER_BB_LEGACY_KEYS = frozenset({
    "recalibrated_rate", "own_bb", "own_bfp", "rolling_league_rate", "pool", "league_pool",
})

MANUAL_MARKET_TYPE_TO_ENGINE_MARKET = {
    "MONEYLINE":"MONEYLINE","ML":"MONEYLINE","GAME_TOTAL":"TOTALS","TOTAL":"TOTALS","O/U":"TOTALS","OU":"TOTALS","RUN_LINE":"RUN_LINE","RL":"RUN_LINE",
    "NRFI":"NRFI","YRFI":"YRFI","FIRST_INNING_TOTAL":"YRFI","FIRST_FIVE_MONEYLINE":"F5_MONEYLINE","FIRST_FIVE_RUN_LINE":"F5_RUN_LINE","FIRST_FIVE_TOTAL":"F5_TOTALS","FIRST_FIVE_TEAM_TOTAL":"F5_TEAM_TOTALS","F5_TEAM_TOTAL":"F5_TEAM_TOTALS",
    "BATTER_HITS":"HITS","HITS":"HITS","BATTER_HOME_RUNS":"HOME_RUNS","HOME_RUNS":"HOME_RUNS","ANYTIME_HOME_RUN":"HOME_RUNS",
    "BATTER_TOTAL_BASES":"TOTAL_BASES","TOTAL_BASES":"TOTAL_BASES","BATTER_RBI":"RBI","RBI":"RBI","RBIS":"RBI","BATTER_RUNS":"RUNS","RUNS":"RUNS",
    "BATTER_STOLEN_BASES":"STOLEN_BASES","STOLEN_BASES":"STOLEN_BASES","BATTER_WALKS":"BATTER_BB","BATTER_BB":"BATTER_BB","WALKS":"BATTER_BB",
    "EXTRA_BASE_HITS":"EXTRA_BASE_HITS","XBH":"EXTRA_BASE_HITS","SINGLES":"SINGLES","DOUBLES":"DOUBLES","TRIPLES":"TRIPLES","BATTER_STRIKEOUTS":"BATTER_K","BATTER_K":"BATTER_K",
    "HITS_RUNS_RBIS":"HITS_RUNS_RBIS","H_R_RBI":"HITS_RUNS_RBIS","HITS_RUNS_STOLEN_BASES":"HITS_RUNS_STOLEN_BASES","H_R_SB":"HITS_RUNS_STOLEN_BASES",
    "RUNS_RBIS":"RUNS_RBIS","R_RBI":"RUNS_RBIS","HITS_STOLEN_BASES":"HITS_STOLEN_BASES","H_SB":"HITS_STOLEN_BASES","HITS_WALKS_STOLEN_BASES":"HITS_WALKS_STOLEN_BASES","H_BB_SB":"HITS_WALKS_STOLEN_BASES",
    "PITCHER_STRIKEOUTS":"PITCHER_K","PITCHER_K":"PITCHER_K","PITCHER_OUTS":"PITCHER_OUTS","OUTS_RECORDED":"PITCHER_OUTS","PITCHER_EARNED_RUNS":"PITCHER_ER","PITCHER_ER":"PITCHER_ER",
    "PITCHER_HITS_ALLOWED":"PITCHER_HITS_ALLOWED","PITCHER_WALKS":"PITCHER_BB","PITCHER_BB":"PITCHER_BB","PITCHER_HITS_WALKS_ER":"PITCHER_HITS_WALKS_ER",
    "EITHER_PITCHER_HITS_ALLOWED":"EITHER_PITCHER_HITS_ALLOWED","EITHER_PITCHER_WALKS":"EITHER_PITCHER_BB","EITHER_PITCHER_BB":"EITHER_PITCHER_BB","EITHER_PITCHER_ER":"EITHER_PITCHER_ER",
    "FIRST_HOME_RUN":"FIRST_HOME_RUN","PITCHER_RECORD_WIN":"PITCHER_RECORD_WIN",
}


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


def _detect_payload_shape(
    features: Any,
    *,
    joint_keys: frozenset[str],
    legacy_keys: frozenset[str],
    label: str,
) -> str:
    """Classify migration payloads in one place and reject mixed contracts."""
    if not isinstance(features, Mapping):
        return "legacy"
    present_joint = sorted(key for key in joint_keys if key in features)
    present_legacy = sorted(key for key in legacy_keys if key in features)
    if present_joint and present_legacy:
        raise EngineDispatchError(
            f"AMBIGUOUS_PROP_PAYLOAD: {label} mixes joint keys={present_joint} "
            f"with legacy keys={present_legacy}"
        )
    return "joint" if present_joint else "legacy"


def _legacy_line_unsupported(market: str, line: float, allowed: tuple[float, ...]) -> EngineDispatchError:
    return EngineDispatchError(
        f"LEGACY_LINE_UNSUPPORTED: {market} line={line}; legacy_allowed={allowed}; "
        "canonical joint payload supports arbitrary non-negative count thresholds"
    )


def _common_output(model_input: Mapping[str, Any], result: Any, model_p: float, market: str) -> dict[str, Any]:
    return {
        "game_id": model_input.get("game_id"), "market": market,
        "entity_id": model_input.get("entity_id"), "line": model_input.get("line"),
        "side": model_input.get("side"), "model_p": float(model_p),
        "model_input_hash": result.model_input_hash, "engine_version": result.engine_version,
        "seed_policy": result.seed_policy, "mc_paths": result.mc_paths,
    }


def legacy_hits_engine_adapter(model_input: Mapping[str, Any]) -> dict[str, Any]:
    if model_input.get("market") != "HITS":
        raise EngineDispatchError("Hits adapter requires market=HITS")
    line = _finite_line(model_input.get("line"))
    if line not in _HITTER_LINES:
        raise _legacy_line_unsupported("HITS", line, _HITTER_LINES)
    side = model_input.get("side")
    if side not in ("OVER", "UNDER"):
        raise EngineDispatchError("HITS side must be OVER or UNDER")
    internal = dict(model_input); internal["market"] = "hits"
    result = simulate_hits(internal, thresholds=(line,))
    p_over = float(result.probs[line])
    return _common_output(model_input, result, p_over if side == "OVER" else 1.0 - p_over, "HITS")


def legacy_total_bases_engine_adapter(model_input: Mapping[str, Any]) -> dict[str, Any]:
    if model_input.get("market") != "TOTAL_BASES":
        raise EngineDispatchError("Total Bases adapter requires market=TOTAL_BASES")
    line = _finite_line(model_input.get("line"))
    if line not in _HITTER_LINES:
        raise _legacy_line_unsupported("TOTAL_BASES", line, _HITTER_LINES)
    side = model_input.get("side")
    if side not in ("OVER", "UNDER"):
        raise EngineDispatchError("TOTAL_BASES side must be OVER or UNDER")
    internal = dict(model_input); internal["market"] = "total_bases"
    result = simulate_total_bases(internal, thresholds=(line,))
    p_over = float(result.probs[line])
    return _common_output(model_input, result, p_over if side == "OVER" else 1.0 - p_over, "TOTAL_BASES")


def legacy_pitcher_bb_engine_adapter(model_input: Mapping[str, Any]) -> dict[str, Any]:
    if model_input.get("market") != "PITCHER_BB":
        raise EngineDispatchError("Pitcher BB adapter requires market=PITCHER_BB")
    line = _finite_line(model_input.get("line"))
    if line not in _BB_LINES:
        raise _legacy_line_unsupported("PITCHER_BB", line, _BB_LINES)
    side = model_input.get("side")
    if side not in ("OVER", "UNDER"):
        raise EngineDispatchError("PITCHER_BB side must be OVER or UNDER")
    internal = dict(model_input); internal["market"] = "pitcher_walks"
    result = simulate_bb(internal, thresholds=(line,))
    p_over = float(result.probs[line])
    return _common_output(model_input, result, p_over if side == "OVER" else 1.0 - p_over, "PITCHER_BB")


hits_engine_adapter = legacy_hits_engine_adapter
total_bases_engine_adapter = legacy_total_bases_engine_adapter
pitcher_bb_engine_adapter = legacy_pitcher_bb_engine_adapter


def hitter_joint_adapter(model_input: Mapping[str, Any]) -> Mapping[str, Any]:
    market = str(model_input.get("market", "")).upper()
    features = model_input.get("features")
    if market == "HITS":
        shape = _detect_payload_shape(
            features, joint_keys=frozenset({"history_pool"}), legacy_keys=_HITS_LEGACY_KEYS, label=market,
        )
        if shape == "legacy":
            return legacy_hits_engine_adapter(model_input)
    elif market == "TOTAL_BASES":
        shape = _detect_payload_shape(
            features, joint_keys=frozenset({"history_pool"}), legacy_keys=_TOTAL_BASES_LEGACY_KEYS, label=market,
        )
        if shape == "legacy":
            return legacy_total_bases_engine_adapter(model_input)
    return price_hitter_market(model_input)


def pitcher_joint_adapter(model_input: Mapping[str, Any]) -> Mapping[str, Any]:
    market = str(model_input.get("market", "")).upper()
    features = model_input.get("features")
    if market == "PITCHER_BB":
        shape = _detect_payload_shape(
            features,
            joint_keys=frozenset({"history_pool", "pitcher_a_history", "pitcher_b_history"}),
            legacy_keys=_PITCHER_BB_LEGACY_KEYS,
            label=market,
        )
        if shape == "legacy":
            return legacy_pitcher_bb_engine_adapter(model_input)
    return price_pitcher_market(model_input)


def resolve_manual_market_type(market_type: str) -> str:
    key = str(market_type or "").strip().upper()
    market = MANUAL_MARKET_TYPE_TO_ENGINE_MARKET.get(key)
    if market is None or market not in engine_registry():
        raise EngineDispatchError(f"NO_ENGINE_FOR_MARKET: {key}")
    return market


def engine_registry() -> dict[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]]:
    registry: dict[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]] = {}
    shared_game_engine = build_shared_game_engine_session()
    shared_f5_engine = build_shared_f5_engine_session()
    for market in sorted(GAME_MARKETS | BINARY_MARKETS):
        if market in STAGE1_GAME_MARKETS:
            registry[market] = shared_game_engine
        elif market in STAGE1_F5_MARKETS:
            registry[market] = shared_f5_engine
        else:
            registry[market] = generic_market_engine_adapter
    for market in sorted(HITTER_MARKETS):
        registry[market] = hitter_joint_adapter
    for market in sorted(PITCHER_MARKETS):
        registry[market] = pitcher_joint_adapter
    registry["HOME_RUNS"] = generic_market_engine_adapter
    return registry