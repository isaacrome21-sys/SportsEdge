#!/usr/bin/env python3
"""SportsEdge fail-closed orchestration layer v0.3.

Reference orchestration contract for live pricing. This version adds hard
candidate-identity binding so a valid Model_P cannot be accidentally priced
against the wrong game, market, entity, line, or side.

PRICE remains market data only; it can never become Model_P. MODEL_STATUS and
BET_STATUS remain separate. Price freshness is checked both at ingress and
immediately before finalization.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

PRICE_TTL_SECONDS = 300
SCHEMA_VERSION = "0.3"
ALLOWED_MODEL_SOURCE_KINDS = {"SPORTSEDGE_MODEL", "SPORTSEDGE_MC"}

# Markets whose current reference contract is player/entity + threshold + side.
# Additions must be explicit; unknown/new markets do not inherit this policy.
BOUND_PLAYER_THRESHOLD_MARKETS = {
    "hits",
    "total_bases",
    "rbi",
    "runs",
    "pitcher_walks",
    "pitcher_strikeouts",
    "pitcher_outs",
    "pitcher_hits",
}


class OrchestrationError(RuntimeError):
    pass


def _utc(ts: datetime) -> datetime:
    if not isinstance(ts, datetime) or ts.tzinfo is None:
        raise OrchestrationError("TIMESTAMP_MISSING_TIMEZONE")
    return ts.astimezone(timezone.utc)


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def american_implied_probability(odds: int) -> float:
    if isinstance(odds, bool) or not isinstance(odds, int) or odds == 0 or -100 < odds < 100:
        raise OrchestrationError("INVALID_AMERICAN_ODDS")
    return (-odds) / ((-odds) + 100.0) if odds < 0 else 100.0 / (odds + 100.0)


@dataclass(frozen=True)
class PriceRecord:
    source_id: str
    provider: str
    source_surface: str
    game_id: str
    market: str
    selection: str
    line: Optional[float]
    american_odds: int
    retrieved_at: datetime
    ttl_seconds: int = PRICE_TTL_SECONDS
    execution_equivalence: str = "UNATTESTED"
    entity_id: Optional[str] = None
    side: Optional[str] = None


@dataclass(frozen=True)
class RunResult:
    schema_version: str
    game_id: str
    market: str
    selection: str
    entity_id: Optional[str]
    side: Optional[str]
    line: Optional[float]
    american_odds: int
    model_status: str
    bet_status: str
    model_p: Optional[float]
    market_implied_p: Optional[float]
    edge: Optional[float]
    mc_paths: Optional[int]
    model_input_hash: Optional[str]
    engine_code_version: Optional[str]
    model_source_kind: str
    price_source_id: str
    price_provider: str
    price_source_surface: str
    price_retrieved_at: str
    price_execution_equivalence: str
    price_age_ingress_seconds: float
    price_age_final_seconds: float
    reason: str
    run_hash: str


def price_age_seconds(price: PriceRecord, now: datetime) -> float:
    return (_utc(now) - _utc(price.retrieved_at)).total_seconds()


def assert_price_fresh(price: PriceRecord, now: datetime, stage: str) -> float:
    if isinstance(price.ttl_seconds, bool) or not isinstance(price.ttl_seconds, int) or price.ttl_seconds <= 0:
        raise OrchestrationError(f"INVALID_PRICE_TTL:{stage}")
    age = price_age_seconds(price, now)
    if age < 0:
        raise OrchestrationError(f"PRICE_FROM_FUTURE:{stage}:{age}")
    if age > price.ttl_seconds:
        raise OrchestrationError(f"STALE_PRICE:{stage}:{age:.3f}>{price.ttl_seconds}")
    return age


def _validate_model_p(p: Any) -> float:
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(float(p)):
        raise OrchestrationError("INVALID_MODEL_P")
    p = float(p)
    if not 0.0 <= p <= 1.0:
        raise OrchestrationError("INVALID_MODEL_P")
    return p


def _same_number(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return False
    try:
        af = float(a)
        bf = float(b)
    except (TypeError, ValueError):
        return False
    return math.isfinite(af) and math.isfinite(bf) and abs(af - bf) <= 1e-12


def _assert_candidate_binding(
    *,
    price: PriceRecord,
    model_input: Dict[str, Any],
    deployment_status: Dict[str, Any],
    engine: Optional[Dict[str, Any]] = None,
) -> None:
    """Bind every authoritative object to one candidate before BET_STATUS."""
    if model_input.get("game_id") != price.game_id:
        raise OrchestrationError("PRICE_MODEL_GAME_MISMATCH")
    if model_input.get("market") != price.market:
        raise OrchestrationError("PRICE_MODEL_MARKET_MISMATCH")

    deployed_market = deployment_status.get("market")
    if deployed_market != price.market:
        raise OrchestrationError("PRICE_DEPLOYMENT_MARKET_MISMATCH")

    if price.market in BOUND_PLAYER_THRESHOLD_MARKETS:
        if not isinstance(price.entity_id, str) or not price.entity_id:
            raise OrchestrationError("PRICE_ENTITY_ID_MISSING")
        if model_input.get("entity_id") != price.entity_id:
            raise OrchestrationError("PRICE_MODEL_ENTITY_MISMATCH")
        if price.line is None:
            raise OrchestrationError("PRICE_LINE_MISSING")
        if price.side not in {"over", "under"}:
            raise OrchestrationError("PRICE_SIDE_INVALID")

    if engine is not None and price.market in BOUND_PLAYER_THRESHOLD_MARKETS:
        if not _same_number(engine.get("line"), price.line):
            raise OrchestrationError("PRICE_ENGINE_LINE_MISMATCH")
        if engine.get("side") != price.side:
            raise OrchestrationError("PRICE_ENGINE_SIDE_MISMATCH")


def run_candidate(
    *,
    price: PriceRecord,
    model_input: Dict[str, Any],
    deployment_status: Dict[str, Any],
    run_started_at: datetime,
    decision_time: datetime,
    engine_fn: Callable[[Dict[str, Any]], Dict[str, Any]],
    mc_fn: Optional[Callable[[Dict[str, Any], int], Dict[str, Any]]] = None,
    mc_paths: int = 25_000,
    min_edge: float = 0.035,
    require_mc: bool = False,
) -> RunResult:
    if deployment_status.get("status") not in {"PASS", "PASS_CAUTION"}:
        raise OrchestrationError(f"DEPLOYMENT_NOT_AUTHORIZED:{deployment_status.get('status')}")
    if isinstance(mc_paths, bool) or not isinstance(mc_paths, int) or mc_paths < 1:
        raise OrchestrationError("INVALID_MC_PATHS")
    if isinstance(min_edge, bool) or not isinstance(min_edge, (int, float)) or not math.isfinite(float(min_edge)) or not 0 <= float(min_edge) <= 1:
        raise OrchestrationError("INVALID_MIN_EDGE")
    if not isinstance(model_input, dict):
        raise OrchestrationError("MODEL_INPUT_INVALID")
    if _utc(decision_time) < _utc(run_started_at):
        raise OrchestrationError("DECISION_TIME_BEFORE_RUN_START")

    expected_input_hash = model_input.get("build_hash")
    if not isinstance(expected_input_hash, str) or not expected_input_hash:
        raise OrchestrationError("MODEL_INPUT_BUILD_HASH_MISSING")

    # Identity binding is checked before expensive inference.
    _assert_candidate_binding(price=price, model_input=model_input, deployment_status=deployment_status)
    age_ingress = assert_price_fresh(price, run_started_at, "INGRESS")

    engine = engine_fn(model_input)
    if not isinstance(engine, dict):
        raise OrchestrationError("ENGINE_OUTPUT_INVALID")
    source_kind = engine.get("source_kind")
    if source_kind not in ALLOWED_MODEL_SOURCE_KINDS:
        raise OrchestrationError(f"MODEL_P_SOURCE_NOT_AUTHORIZED:{source_kind}")
    model_p = _validate_model_p(engine.get("model_p"))
    model_input_hash = engine.get("model_input_hash")
    if model_input_hash != expected_input_hash:
        raise OrchestrationError("MODEL_INPUT_HASH_MISMATCH")
    engine_code_version = engine.get("engine_code_version")
    if engine_code_version is not None and (not isinstance(engine_code_version, str) or not engine_code_version):
        raise OrchestrationError("ENGINE_CODE_VERSION_INVALID")

    # Bind the engine's priced threshold and side to the actual sportsbook quote.
    _assert_candidate_binding(price=price, model_input=model_input, deployment_status=deployment_status, engine=engine)

    native_mc_present = ("mc_status" in engine) or ("mc_paths" in engine)
    used_paths: Optional[int] = None
    if native_mc_present:
        if engine.get("mc_status") != "PASS" or engine.get("mc_paths") != mc_paths:
            raise OrchestrationError("NATIVE_MC_ATTESTATION_INVALID")
        used_paths = mc_paths
    if mc_fn is not None:
        if native_mc_present:
            raise OrchestrationError("AMBIGUOUS_MC_ATTESTATION")
        mc = mc_fn(model_input, mc_paths)
        if not isinstance(mc, dict) or mc.get("paths") != mc_paths or mc.get("status") != "PASS":
            raise OrchestrationError("MC_ATTESTATION_INVALID")
        used_paths = mc_paths
    if require_mc and used_paths is None:
        raise OrchestrationError("MC_ATTESTATION_MISSING")

    # SECOND price gate: after inference/MC and immediately before pricing can
    # affect BET_STATUS.
    age_final = assert_price_fresh(price, decision_time, "FINALIZATION")

    market_p = american_implied_probability(price.american_odds)
    edge = model_p - market_p
    model_status = str(deployment_status.get("status"))
    bet_status = "PASS" if edge >= float(min_edge) else "NO_BET_EDGE"
    reason = "EDGE_CLEARS_THRESHOLD" if bet_status == "PASS" else "EDGE_BELOW_THRESHOLD"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "game_id": price.game_id,
        "market": price.market,
        "selection": price.selection,
        "entity_id": price.entity_id,
        "side": price.side,
        "line": price.line,
        "american_odds": price.american_odds,
        "model_status": model_status,
        "bet_status": bet_status,
        "model_p": model_p,
        "market_implied_p": market_p,
        "edge": edge,
        "mc_paths": used_paths,
        "model_input_hash": model_input_hash,
        "engine_code_version": engine_code_version,
        "model_source_kind": source_kind,
        "price_source_id": price.source_id,
        "price_provider": price.provider,
        "price_source_surface": price.source_surface,
        "price_retrieved_at": _utc(price.retrieved_at).isoformat(),
        "price_execution_equivalence": price.execution_equivalence,
        "price_age_ingress_seconds": age_ingress,
        "price_age_final_seconds": age_final,
        "reason": reason,
    }
    run_hash = hashlib.sha256(_canonical(payload).encode()).hexdigest()
    return RunResult(run_hash=run_hash, **payload)


def result_to_dict(result: RunResult) -> Dict[str, Any]:
    return asdict(result)
