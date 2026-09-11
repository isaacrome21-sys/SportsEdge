from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any, Callable, Mapping

from .candidate_binding import bind_candidate, bind_model_to_quote
from .devig import devig_with_policy
from .edge_floors import (
    DEFAULT_EDGE_FLOOR_CONFIG,
    load_edge_floor_config,
    require_frozen_devig_policy,
    require_production_edge_floor,
)
from .price_ttl import double_ttl_gate
from .truth_gate import BetDecision, decide_bet


class OrchestrationError(ValueError):
    pass


BANNED_MODEL_INPUT_KEYS = {
    "sportsbook_probability", "implied_probability", "market_probability",
    "american_odds", "decimal_odds", "sportsbook_price", "dk_probability",
}


@dataclass(frozen=True)
class RunResult:
    market: str
    model_p: float | None
    bet_status: str
    decision: BetDecision | None
    reason: str
    model_input_hash: str | None = None
    distribution_sha256: str | None = None
    readout_sha256: str | None = None
    readout_version: str | None = None
    engine_version: str | None = None
    runtime_path: str | None = None
    seed_policy: str | None = None
    mc_paths: int | None = None
    push_probability: float = 0.0
    book_key: str | None = None
    sportsbook: str | None = None
    quote_retrieved_at: str | None = None
    offer_id: str | None = None


def _reject_market_leakage(model_input: Mapping[str, Any]) -> None:
    present = BANNED_MODEL_INPUT_KEYS.intersection(model_input.keys())
    if present:
        raise OrchestrationError(f"sportsbook/market data prohibited in Model_Input: {sorted(present)}")


def _optional_sha256(output: Mapping[str, Any], key: str) -> str | None:
    value = output.get(key)
    if value is None:
        return None
    text = str(value).lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise OrchestrationError(f"engine output malformed {key}")
    return text


def _optional_text(output: Mapping[str, Any], key: str) -> str | None:
    value = output.get(key)
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        raise OrchestrationError(f"engine output malformed {key}")
    return text


def _optional_nonnegative_int(output: Mapping[str, Any], key: str) -> int | None:
    value = output.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        raise OrchestrationError(f"engine output malformed {key}")
    try:
        parsed = int(value)
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise OrchestrationError(f"engine output malformed {key}") from exc
    if parsed < 0 or numeric != parsed:
        raise OrchestrationError(f"engine output malformed {key}")
    return parsed


def _probability(value: Any, *, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise OrchestrationError(f"engine output malformed {field}") from exc
    if not isfinite(out) or not 0.0 <= out <= 1.0:
        raise OrchestrationError(f"engine output malformed {field}")
    return out


def _quote_identity(quote: Mapping[str, Any]) -> tuple[str, str | None, str, str | None]:
    book_key = str(quote.get("book_key") or "").strip()
    if not book_key:
        raise OrchestrationError("quote book_key missing")
    sportsbook_raw = quote.get("sportsbook")
    sportsbook = str(sportsbook_raw).strip() if sportsbook_raw not in (None, "") else None
    retrieved = quote.get("retrieved_at")
    if not isinstance(retrieved, datetime) or retrieved.tzinfo is None or retrieved.utcoffset() is None:
        raise OrchestrationError("quote retrieved_at must be timezone-aware")
    offer_raw = quote.get("offer_id")
    offer_id = str(offer_raw).strip() if offer_raw not in (None, "") else None
    return book_key, sportsbook, retrieved.isoformat(), offer_id


def _candidate(market: str, model_p: float, reason: str, common: Mapping[str, Any]) -> RunResult:
    return RunResult(market, model_p, "MODEL_CANDIDATE", None, f"OFFICIAL_BLOCKED:{reason}", **dict(common))


def run_candidate(*, model_input: Mapping[str, Any], quote: Mapping[str, Any], paired_quote: Mapping[str, Any] | None = None, deployment: Mapping[str, Any], engine_fn: Callable[[Mapping[str, Any]], Mapping[str, Any]], ingestion_now: datetime, finalization_now: datetime, edge_floor_config_path: str = DEFAULT_EDGE_FLOOR_CONFIG, kelly_multiplier: float = 0.25) -> RunResult:
    """Run market-blind inference first, then resolve OFFICIAL-only gates.

    Hard integrity failures erase the candidate and return BLOCKED. Promotion-only
    failures retain a genuine identity-bound Model_P as MODEL_CANDIDATE. A missing
    opposite price therefore blocks devig/OFFICIAL but does not invent a no-vig
    probability or destroy valid model inference.
    """
    market = str(model_input.get("market", "UNKNOWN"))
    try:
        _reject_market_leakage(model_input)
        double_ttl_gate(quote, ingestion_now, finalization_now)
        book_key, sportsbook, quote_retrieved_at, offer_id = _quote_identity(quote)
        if not isinstance(deployment, Mapping):
            raise OrchestrationError("deployment attestation missing or malformed")

        output = dict(engine_fn(model_input))
        if "model_p" not in output:
            raise OrchestrationError("engine output missing model_p")
        for key in ("game_id", "market", "entity_id", "line", "side"):
            if key not in output and key in model_input:
                output[key] = model_input[key]

        model_p = _probability(output["model_p"], field="model_p")
        push_probability = _probability(output.get("push_p", 0.0), field="push_p")
        if model_p + push_probability > 1.0 + 1e-12:
            raise OrchestrationError("engine output model_p + push_p exceeds 1")
        runtime_path = _optional_text(output, "runtime_path")
        model_input_hash = _optional_sha256(output, "model_input_hash")
        distribution_sha256 = _optional_sha256(output, "distribution_sha256")
        readout_sha256 = _optional_sha256(output, "readout_sha256")
        readout_version = _optional_text(output, "readout_version")
        engine_version = _optional_text(output, "engine_version")
        seed_policy = _optional_text(output, "seed_policy")
        mc_paths = _optional_nonnegative_int(output, "mc_paths")

        common = dict(
            model_input_hash=model_input_hash,
            distribution_sha256=distribution_sha256,
            readout_sha256=readout_sha256,
            readout_version=readout_version,
            engine_version=engine_version,
            runtime_path=runtime_path,
            seed_policy=seed_policy,
            mc_paths=mc_paths,
            push_probability=push_probability,
            book_key=book_key,
            sportsbook=sportsbook,
            quote_retrieved_at=quote_retrieved_at,
            offer_id=offer_id,
        )

        if deployment.get("eligible") is not True:
            bind_model_to_quote(output, quote)
            return _candidate(
                market,
                model_p,
                str(deployment.get("reason") or "DEPLOYMENT_NOT_ELIGIBLE"),
                common,
            )

        deployed = {"market": market, **dict(deployment)}
        bind_candidate(output, quote, deployed)
        if runtime_path == "LEGACY_COMPAT":
            return _candidate(market, model_p, "LEGACY_COMPAT_PATH_NOT_PROMOTABLE", common)

        try:
            floor = require_production_edge_floor(market=market, path=edge_floor_config_path)
            floor_config = load_edge_floor_config(edge_floor_config_path)
            devig_policy = require_frozen_devig_policy(config=floor_config)
        except Exception as exc:
            return _candidate(market, model_p, f"{type(exc).__name__}:{exc}", common)

        if not isinstance(paired_quote, Mapping):
            return _candidate(market, model_p, "PAIRED_PRICE_REQUIRED_FOR_DEVIG", common)
        try:
            double_ttl_gate(paired_quote, ingestion_now, finalization_now)
            priced = devig_with_policy(quote, paired_quote, policy=devig_policy)
        except Exception as exc:
            return _candidate(market, model_p, f"{type(exc).__name__}:{exc}", common)

        decision = decide_bet(
            model_p, quote["american_odds"],
            fair_market_probability=priced.fair_probability_for_decision,
            bound=True, fresh=True, deployed=True,
            edge_floor=float(floor.value_probability_points), kelly_multiplier=kelly_multiplier,
            push_probability=push_probability,
        )
        return RunResult(market, model_p, decision.bet_status, decision, "ok", **common)
    except Exception as exc:
        return RunResult(market, None, "BLOCKED", None, f"{type(exc).__name__}: {exc}")


def run_slate(candidates: list[Mapping[str, Any]], *, engines: Mapping[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]], deployments: Mapping[str, Mapping[str, Any]], ingestion_now: datetime, finalization_now: datetime, edge_floor_config_path: str = DEFAULT_EDGE_FLOOR_CONFIG, kelly_multiplier: float = 0.25) -> list[RunResult]:
    results: list[RunResult] = []
    for item in candidates:
        model_input = item.get("model_input")
        quote = item.get("quote")
        paired_quote = item.get("paired_quote")
        if not isinstance(model_input, Mapping) or not isinstance(quote, Mapping):
            results.append(RunResult("UNKNOWN", None, "BLOCKED", None, "candidate missing model_input/quote"))
            continue
        market = model_input.get("market")
        engine = engines.get(market)
        deployment = deployments.get(market)
        if engine is None or deployment is None:
            results.append(RunResult(str(market), None, "BLOCKED", None, "unsupported or undeployed market"))
            continue
        results.append(run_candidate(
            model_input=model_input, quote=quote, paired_quote=paired_quote,
            deployment=deployment, engine_fn=engine,
            ingestion_now=ingestion_now, finalization_now=finalization_now,
            edge_floor_config_path=edge_floor_config_path, kelly_multiplier=kelly_multiplier,
        ))
    return results
