#!/usr/bin/env python3
"""SportsEdge fail-closed orchestration layer v0.1.

This module coordinates already-validated components without inventing model
inputs or probabilities. PRICE is market data only and is never permitted to
become Model_P. MODEL_STATUS and BET_STATUS remain separate.

Critical invariant: price freshness is checked twice: at ingestion and again
immediately before BET_STATUS finalization. A price that expires while the
pipeline is running cannot authorize a wager.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

PRICE_TTL_SECONDS = 300
SCHEMA_VERSION = "0.1"


class OrchestrationError(RuntimeError):
    pass


def _utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
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


@dataclass(frozen=True)
class RunResult:
    schema_version: str
    game_id: str
    market: str
    selection: str
    model_status: str
    bet_status: str
    model_p: Optional[float]
    market_implied_p: Optional[float]
    edge: Optional[float]
    mc_paths: Optional[int]
    model_input_hash: Optional[str]
    price_source_id: str
    price_age_ingress_seconds: float
    price_age_final_seconds: float
    reason: str
    run_hash: str


def price_age_seconds(price: PriceRecord, now: datetime) -> float:
    return (_utc(now) - _utc(price.retrieved_at)).total_seconds()


def assert_price_fresh(price: PriceRecord, now: datetime, stage: str) -> float:
    if price.ttl_seconds <= 0:
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
) -> RunResult:
    """Run one candidate through parity -> price ingress -> engine -> MC -> price final gate.

    `engine_fn` must return a dict containing model_p and model_input_hash.
    `mc_fn`, when supplied, must return an attestation with paths == mc_paths.
    No sportsbook-derived probability is accepted as Model_P.
    """
    if deployment_status.get("status") not in {"PASS", "PASS_CAUTION"}:
        raise OrchestrationError(f"DEPLOYMENT_NOT_AUTHORIZED:{deployment_status.get('status')}")
    if mc_paths < 1:
        raise OrchestrationError("INVALID_MC_PATHS")

    age_ingress = assert_price_fresh(price, run_started_at, "INGRESS")

    engine = engine_fn(model_input)
    if not isinstance(engine, dict):
        raise OrchestrationError("ENGINE_OUTPUT_INVALID")
    if engine.get("source_kind") in {"SPORTSBOOK_PROBABILITY", "MARKET_PROBABILITY", "CONSENSUS_PROBABILITY"}:
        raise OrchestrationError("MODEL_P_SOURCE_BANNED")
    model_p = _validate_model_p(engine.get("model_p"))
    model_input_hash = engine.get("model_input_hash")
    if not isinstance(model_input_hash, str) or not model_input_hash:
        raise OrchestrationError("MODEL_INPUT_HASH_MISSING")

    used_paths: Optional[int] = None
    if mc_fn is not None:
        mc = mc_fn(model_input, mc_paths)
        if not isinstance(mc, dict) or mc.get("paths") != mc_paths or mc.get("status") != "PASS":
            raise OrchestrationError("MC_ATTESTATION_INVALID")
        used_paths = mc_paths

    # SECOND price gate: intentionally after engine/MC work and immediately
    # before pricing can affect BET_STATUS.
    age_final = assert_price_fresh(price, decision_time, "FINALIZATION")

    market_p = american_implied_probability(price.american_odds)
    edge = model_p - market_p
    model_status = str(deployment_status.get("status"))
    bet_status = "PASS" if edge >= min_edge else "NO_BET_EDGE"
    reason = "EDGE_CLEARS_THRESHOLD" if bet_status == "PASS" else "EDGE_BELOW_THRESHOLD"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "game_id": price.game_id,
        "market": price.market,
        "selection": price.selection,
        "model_status": model_status,
        "bet_status": bet_status,
        "model_p": model_p,
        "market_implied_p": market_p,
        "edge": edge,
        "mc_paths": used_paths,
        "model_input_hash": model_input_hash,
        "price_source_id": price.source_id,
        "price_age_ingress_seconds": age_ingress,
        "price_age_final_seconds": age_final,
        "reason": reason,
    }
    run_hash = hashlib.sha256(_canonical(payload).encode()).hexdigest()
    return RunResult(run_hash=run_hash, **payload)


def result_to_dict(result: RunResult) -> Dict[str, Any]:
    return asdict(result)
