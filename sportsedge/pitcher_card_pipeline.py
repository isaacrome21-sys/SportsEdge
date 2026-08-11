"""End-to-end card pipeline for validated pitcher walk props."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Mapping

from .engine_registry import engine_registry
from .live_slate import LiveGame, LiveSlateError
from .orchestrator import run_candidate
from .pitcher_live import assemble_pitcher_bb_candidate
from .runtime import runtime_deployments


@dataclass(frozen=True)
class PitcherCardResult:
    game_id: str
    market: str
    entity_id: str
    line: Any
    side: str
    american_odds: Any
    model_p: float | None
    bet_status: str
    reason: str


def _identity(quote: Mapping[str, Any]) -> tuple[str, str, str, Any, str]:
    try:
        game_id = str(quote["game_id"])
        market = str(quote["market"])
        entity_id = str(quote["entity_id"])
        line = quote["line"]
        side = str(quote["side"])
    except Exception as exc:
        raise LiveSlateError("quote missing canonical identity") from exc
    return game_id, market, entity_id, line, side


def run_pitcher_bb_card(*, games: list[LiveGame], feature_rows: list[Mapping[str, Any]], quotes: list[Mapping[str, Any]], ingestion_now: datetime, finalization_now: datetime, registry_path: str = "config/deployments.json", min_edge: float = 0.0, kelly_multiplier: float = 0.25) -> list[PitcherCardResult]:
    game_map = {str(g.game_pk): g for g in games}
    if len(game_map) != len(games):
        raise LiveSlateError("duplicate live game")
    feature_map: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for row in feature_rows:
        try:
            key = (str(row["game_pk"]), str(row["player_id"]), str(row["market"]))
        except Exception as exc:
            raise LiveSlateError("feature row missing game/player/market identity") from exc
        if key in feature_map:
            raise LiveSlateError(f"duplicate feature row: {key}")
        feature_map[key] = row

    deployments = runtime_deployments(registry_path)
    engine = engine_registry().get("PITCHER_BB")
    deployment = deployments.get("PITCHER_BB")
    out: list[PitcherCardResult] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for quote in quotes:
        odds = quote.get("american_odds") if isinstance(quote, Mapping) else None
        try:
            game_id, market, entity_id, line, side = _identity(quote)
            qkey = (game_id, market, entity_id, repr(line), side)
            if qkey in seen:
                raise LiveSlateError("duplicate sportsbook quote candidate")
            seen.add(qkey)
            if market != "PITCHER_BB":
                raise LiveSlateError("unsupported pitcher market")
            game = game_map.get(game_id)
            if game is None:
                raise LiveSlateError("live game missing for quote")
            feature = feature_map.get((game_id, entity_id, market))
            if feature is None:
                raise LiveSlateError("feature snapshot missing for quote")
            if engine is None or deployment is None:
                raise LiveSlateError("pitcher BB engine/deployment registration missing")
            candidate = assemble_pitcher_bb_candidate(game=game, feature_row=feature, quote=quote)
            rr = run_candidate(
                model_input=candidate["model_input"], quote=candidate["quote"],
                deployment=deployment, engine_fn=engine,
                ingestion_now=ingestion_now, finalization_now=finalization_now,
                min_edge=min_edge, kelly_multiplier=kelly_multiplier,
            )
            out.append(PitcherCardResult(game_id, market, entity_id, line, side, odds, rr.model_p, rr.bet_status, rr.reason))
        except Exception as exc:
            try:
                game_id, market, entity_id, line, side = _identity(quote)
            except Exception:
                game_id, market, entity_id, line, side = "UNKNOWN", "UNKNOWN", "UNKNOWN", None, "UNKNOWN"
            out.append(PitcherCardResult(game_id, market, entity_id, line, side, odds, None, "BLOCKED", f"{type(exc).__name__}: {exc}"))
    return out


def pitcher_card_result_to_dict(result: PitcherCardResult) -> dict[str, Any]:
    return asdict(result)
