"""End-to-end card assembly for validated hitter markets."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Mapping

from .engine_registry import engine_registry
from .live_slate import LiveGame, LiveSlateError, SUPPORTED_HITTER_MARKETS, assemble_hitter_candidate
from .orchestrator import run_candidate
from .quote_bridge import validate_canonical_quote
from .runtime import runtime_deployments


@dataclass(frozen=True)
class CardResult:
    game_id: str
    market: str
    entity_id: str
    line: Any
    side: str
    american_odds: Any
    model_p: float | None
    bet_status: str
    reason: str


def _quote_identity(quote: Mapping[str, Any]) -> tuple[str, str, str, Any, str]:
    q = validate_canonical_quote(quote)
    return q["game_id"], q["market"], q["entity_id"], q["line"], q["side"]


def run_hitter_card(*, games: list[LiveGame], feature_rows: list[Mapping[str, Any]], quotes: list[Mapping[str, Any]], ingestion_now: datetime, finalization_now: datetime, registry_path: str = "config/deployments.json", require_confirmed_lineup: bool = True, min_edge: float = 0.0, kelly_multiplier: float = 0.25) -> list[CardResult]:
    game_map: dict[str, LiveGame] = {}
    for game in games:
        key = str(game.game_pk)
        if key in game_map:
            raise LiveSlateError(f"duplicate live game: {key}")
        game_map[key] = game

    feature_map: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for row in feature_rows:
        try:
            key = (str(row["game_pk"]), str(row["player_id"]), str(row["market"]))
        except Exception as exc:
            raise LiveSlateError("feature row missing game_pk/player_id/market") from exc
        if key in feature_map:
            raise LiveSlateError(f"duplicate feature row: {key}")
        feature_map[key] = row

    deployments = runtime_deployments(registry_path)
    engines = engine_registry()
    seen_quotes: set[tuple[str, str, str, str, str, str, bool]] = set()
    out: list[CardResult] = []

    for raw_quote in quotes:
        odds = raw_quote.get("american_odds") if isinstance(raw_quote, Mapping) else None
        try:
            quote = validate_canonical_quote(raw_quote)
            game_id, market, entity_id, line, side = _quote_identity(quote)
            qkey = (game_id, market, entity_id, repr(line), side, quote["book_key"], quote["is_alternate"])
            if qkey in seen_quotes:
                raise LiveSlateError("duplicate sportsbook quote candidate")
            seen_quotes.add(qkey)
            if market not in SUPPORTED_HITTER_MARKETS:
                raise LiveSlateError(f"unsupported hitter market: {market}")
            game = game_map.get(game_id)
            if game is None:
                raise LiveSlateError("live game missing for quote")
            feature = feature_map.get((game_id, entity_id, market))
            if feature is None:
                raise LiveSlateError("market-specific feature snapshot missing for quote")
            candidate = assemble_hitter_candidate(game=game, market=market, feature_row=feature, quote=quote, require_confirmed_lineup=require_confirmed_lineup)
            engine = engines.get(market)
            deployment = deployments.get(market)
            if engine is None or deployment is None:
                raise LiveSlateError("market engine/deployment registration missing")
            rr = run_candidate(model_input=candidate["model_input"], quote=candidate["quote"], deployment=deployment, engine_fn=engine, ingestion_now=ingestion_now, finalization_now=finalization_now, min_edge=min_edge, kelly_multiplier=kelly_multiplier)
            out.append(CardResult(game_id, market, entity_id, line, side, odds, rr.model_p, rr.bet_status, rr.reason))
        except Exception as exc:
            try:
                game_id, market, entity_id, line, side = _quote_identity(raw_quote)
            except Exception:
                game_id, market, entity_id, line, side = "UNKNOWN", "UNKNOWN", "UNKNOWN", None, "UNKNOWN"
            out.append(CardResult(game_id, market, entity_id, line, side, odds, None, "BLOCKED", f"{type(exc).__name__}: {exc}"))
    return out


def card_result_to_dict(result: CardResult) -> dict[str, Any]:
    return asdict(result)
