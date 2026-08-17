from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping

from .candidate_binding import bind_candidate
from .devig import multiplicative_devig
from .edge_floors import DEFAULT_EDGE_FLOOR_CONFIG, require_production_edge_floor
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


def _reject_market_leakage(model_input: Mapping[str, Any]) -> None:
    present = BANNED_MODEL_INPUT_KEYS.intersection(model_input.keys())
    if present:
        raise OrchestrationError(f"sportsbook/market data prohibited in Model_Input: {sorted(present)}")


def run_candidate(*, model_input: Mapping[str, Any], quote: Mapping[str, Any], paired_quote: Mapping[str, Any] | None = None, deployment: Mapping[str, Any], engine_fn: Callable[[Mapping[str, Any]], Mapping[str, Any]], ingestion_now: datetime, finalization_now: datetime, edge_floor_config_path: str = DEFAULT_EDGE_FLOOR_CONFIG, kelly_multiplier: float = 0.25) -> RunResult:
    """Run one candidate end-to-end. Any integrity failure returns BLOCKED, never a guessed bet."""
    market = str(model_input.get("market", "UNKNOWN"))
    try:
        _reject_market_leakage(model_input)
        if not isinstance(paired_quote, Mapping):
            raise OrchestrationError("PAIRED_PRICE_REQUIRED_FOR_DEVIG")
        double_ttl_gate(quote, ingestion_now, finalization_now)
        double_ttl_gate(paired_quote, ingestion_now, finalization_now)
        devig = multiplicative_devig(quote, paired_quote)
        output = dict(engine_fn(model_input))
        if "model_p" not in output:
            raise OrchestrationError("engine output missing model_p")
        for key in ("game_id", "market", "entity_id", "line", "side"):
            if key not in output and key in model_input:
                output[key] = model_input[key]
        bind_candidate(output, quote, deployment)
        floor = require_production_edge_floor(market=market, path=edge_floor_config_path)
        decision = decide_bet(
            output["model_p"], quote["american_odds"],
            fair_market_probability=devig.candidate_fair_probability,
            bound=True, fresh=True, deployed=deployment.get("eligible") is True,
            edge_floor=float(floor.value_probability_points), kelly_multiplier=kelly_multiplier,
        )
        return RunResult(market, float(output["model_p"]), decision.bet_status, decision, "ok")
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
