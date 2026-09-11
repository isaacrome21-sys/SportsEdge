"""Unified MLB card execution through one canonical market path."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Mapping

from .edge_floors import DEFAULT_EDGE_FLOOR_CONFIG
from .generic_card_pipeline import DECISION_STATUSES, GENERIC_MARKETS, run_generic_card
from .live_slate import LiveGame
from .quote_bridge import validate_canonical_quote

SUPPORTED_MARKETS = GENERIC_MARKETS


@dataclass(frozen=True)
class UnifiedCardResult:
    game_id: str
    market: str
    entity_id: str
    line: Any
    side: str
    american_odds: Any
    model_p: float | None
    bet_status: str
    reason: str
    shadow_status: str | None = None
    implied_probability: float | None = None
    edge: float | None = None
    ev_per_dollar: float | None = None
    model_input_hash: str | None = None
    distribution_sha256: str | None = None
    readout_sha256: str | None = None
    readout_version: str | None = None
    engine_version: str | None = None
    seed_policy: str | None = None
    mc_paths: int | None = None
    book_key: str | None = None
    sportsbook: str | None = None
    quote_retrieved_at: str | None = None
    offer_id: str | None = None
    raw_implied_probability: float | None = None
    market_no_vig_p_status: str | None = None


def _convert(result) -> UnifiedCardResult:
    return UnifiedCardResult(
        game_id=result.game_id,
        market=result.market,
        entity_id=result.entity_id,
        line=result.line,
        side=result.side,
        american_odds=result.american_odds,
        model_p=result.model_p,
        bet_status=result.bet_status,
        reason=result.reason,
        shadow_status=getattr(result, "shadow_status", None),
        implied_probability=getattr(result, "implied_probability", None),
        edge=getattr(result, "edge", None),
        ev_per_dollar=getattr(result, "ev_per_dollar", None),
        model_input_hash=getattr(result, "model_input_hash", None),
        distribution_sha256=getattr(result, "distribution_sha256", None),
        readout_sha256=getattr(result, "readout_sha256", None),
        readout_version=getattr(result, "readout_version", None),
        engine_version=getattr(result, "engine_version", None),
        seed_policy=getattr(result, "seed_policy", None),
        mc_paths=getattr(result, "mc_paths", None),
        book_key=getattr(result, "book_key", None),
        sportsbook=getattr(result, "sportsbook", None),
        quote_retrieved_at=getattr(result, "quote_retrieved_at", None),
        offer_id=getattr(result, "offer_id", None),
        raw_implied_probability=getattr(result, "raw_implied_probability", None),
        market_no_vig_p_status=getattr(result, "market_no_vig_p_status", None),
    )


def _assert_ledger_precondition(result: UnifiedCardResult) -> None:
    modeled = result.model_p is not None
    decided = result.bet_status in DECISION_STATUSES
    if modeled != decided:
        raise RuntimeError(
            "priced decision ledger invariant violated: "
            f"market={result.market} status={result.bet_status} model_p={result.model_p}"
        )


def run_unified_card(
    *,
    games: list[LiveGame],
    feature_rows: list[Mapping[str, Any]],
    quotes: list[Mapping[str, Any]],
    ingestion_now: datetime,
    finalization_now: datetime,
    registry_path: str = "config/deployments.json",
    require_confirmed_lineup: bool = True,
    edge_floor_config_path: str = DEFAULT_EDGE_FLOOR_CONFIG,
    kelly_multiplier: float = 0.25,
) -> list[UnifiedCardResult]:
    indexed: list[tuple[int, Mapping[str, Any]]] = []
    output: dict[int, UnifiedCardResult] = {}
    for i, raw_quote in enumerate(quotes):
        try:
            quote = validate_canonical_quote(raw_quote)
            market = str(quote["market"])
            if market not in SUPPORTED_MARKETS:
                raise ValueError(f"unsupported unified market: {market}")
            indexed.append((i, quote))
        except Exception as exc:
            output[i] = UnifiedCardResult(
                "UNKNOWN", "UNKNOWN", "UNKNOWN", None, "UNKNOWN", None,
                None, "BLOCKED", f"{type(exc).__name__}: {exc}",
            )

    if indexed:
        results = run_generic_card(
            games=games,
            feature_rows=feature_rows,
            quotes=[q for _, q in indexed],
            ingestion_now=ingestion_now,
            finalization_now=finalization_now,
            registry_path=registry_path,
            require_confirmed_lineup=require_confirmed_lineup,
            edge_floor_config_path=edge_floor_config_path,
            kelly_multiplier=kelly_multiplier,
        )
        if len(results) != len(indexed):
            raise RuntimeError("canonical pipeline changed quote cardinality")
        for (i, _), result in zip(indexed, results):
            converted = _convert(result)
            _assert_ledger_precondition(converted)
            output[i] = converted
    if len(output) != len(quotes):
        raise RuntimeError("unified runner failed to preserve quote cardinality")
    return [output[i] for i in range(len(quotes))]


def unified_result_to_dict(result: UnifiedCardResult) -> dict[str, Any]:
    return asdict(result)
