"""Unified card execution with explicit market isolation."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Mapping

from .card_pipeline import run_hitter_card
from .live_slate import LiveGame
from .pitcher_card_pipeline import run_pitcher_bb_card
from .quote_bridge import validate_canonical_quote

HITTER_MARKETS = frozenset({"HITS", "TOTAL_BASES"})
PITCHER_MARKETS = frozenset({"PITCHER_BB"})
SUPPORTED_MARKETS = HITTER_MARKETS | PITCHER_MARKETS


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


def _identity(raw: Mapping[str, Any]) -> tuple[str, str, str, Any, str, Any]:
    q = validate_canonical_quote(raw)
    return q["game_id"], q["market"], q["entity_id"], q["line"], q["side"], q["american_odds"]


def _convert(result) -> UnifiedCardResult:
    return UnifiedCardResult(result.game_id, result.market, result.entity_id, result.line, result.side, result.american_odds, result.model_p, result.bet_status, result.reason)


def run_unified_card(*, games: list[LiveGame], feature_rows: list[Mapping[str, Any]], quotes: list[Mapping[str, Any]], ingestion_now: datetime, finalization_now: datetime, registry_path: str = "config/deployments.json", require_confirmed_lineup: bool = True, min_edge: float = 0.0, kelly_multiplier: float = 0.25) -> list[UnifiedCardResult]:
    indexed_hitter: list[tuple[int, Mapping[str, Any]]] = []
    indexed_pitcher: list[tuple[int, Mapping[str, Any]]] = []
    output: dict[int, UnifiedCardResult] = {}

    for i, raw_quote in enumerate(quotes):
        try:
            quote = validate_canonical_quote(raw_quote)
            game_id, market, entity_id, line, side, odds = _identity(quote)
        except Exception as exc:
            output[i] = UnifiedCardResult("UNKNOWN", "UNKNOWN", "UNKNOWN", None, "UNKNOWN", None, None, "BLOCKED", f"{type(exc).__name__}: {exc}")
            continue
        if market in HITTER_MARKETS:
            indexed_hitter.append((i, quote))
        elif market in PITCHER_MARKETS:
            indexed_pitcher.append((i, quote))
        else:
            output[i] = UnifiedCardResult(game_id, market, entity_id, line, side, odds, None, "BLOCKED", f"unsupported unified market: {market}")

    if indexed_hitter:
        results = run_hitter_card(games=games, feature_rows=feature_rows, quotes=[q for _, q in indexed_hitter], ingestion_now=ingestion_now, finalization_now=finalization_now, registry_path=registry_path, require_confirmed_lineup=require_confirmed_lineup, min_edge=min_edge, kelly_multiplier=kelly_multiplier)
        if len(results) != len(indexed_hitter):
            raise RuntimeError("hitter pipeline changed quote cardinality")
        for (i, _), result in zip(indexed_hitter, results):
            output[i] = _convert(result)

    if indexed_pitcher:
        results = run_pitcher_bb_card(games=games, feature_rows=feature_rows, quotes=[q for _, q in indexed_pitcher], ingestion_now=ingestion_now, finalization_now=finalization_now, registry_path=registry_path, min_edge=min_edge, kelly_multiplier=kelly_multiplier)
        if len(results) != len(indexed_pitcher):
            raise RuntimeError("pitcher pipeline changed quote cardinality")
        for (i, _), result in zip(indexed_pitcher, results):
            output[i] = _convert(result)

    if len(output) != len(quotes):
        raise RuntimeError("unified runner failed to preserve quote cardinality")
    return [output[i] for i in range(len(quotes))]


def unified_result_to_dict(result: UnifiedCardResult) -> dict[str, Any]:
    return asdict(result)
