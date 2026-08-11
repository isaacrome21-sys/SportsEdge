"""End-to-end card pipeline for validated pitcher walk props."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Mapping

from .engine_registry import engine_registry
from .game_state import require_mlb_pregame
from .live_slate import LiveGame, LiveSlateError
from .orchestrator import run_candidate
from .pitcher_live import assemble_pitcher_bb_candidate
from .quote_bridge import validate_canonical_quote
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
    implied_probability: float | None = None
    edge: float | None = None
    ev_per_dollar: float | None = None
    kelly_fraction: float | None = None


def _identity(quote: Mapping[str, Any]) -> tuple[str, str, str, Any, str]:
    q = validate_canonical_quote(quote)
    return q["game_id"], q["market"], q["entity_id"], q["line"], q["side"]


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
            if dict(feature_map[key]) != dict(row):
                raise LiveSlateError(f"conflicting duplicate feature row: {key}")
            continue
        feature_map[key] = row

    deployments = runtime_deployments(registry_path)
    engine = engine_registry().get("PITCHER_BB")
    deployment = deployments.get("PITCHER_BB")
    out: list[PitcherCardResult] = []
    seen: set[tuple[str, str, str, str, str, str, bool]] = set()
    for raw_quote in quotes:
        odds = raw_quote.get("american_odds") if isinstance(raw_quote, Mapping) else None
        try:
            quote = validate_canonical_quote(raw_quote)
            game_id, market, entity_id, line, side = _identity(quote)
            qkey = (game_id, market, entity_id, repr(line), side, quote["book_key"], quote["is_alternate"])
            if qkey in seen:
                raise LiveSlateError("duplicate sportsbook quote candidate")
            seen.add(qkey)
            if market != "PITCHER_BB":
                raise LiveSlateError("unsupported pitcher market")
            game = game_map.get(game_id)
            if game is None:
                raise LiveSlateError("live game missing for quote")
            require_mlb_pregame(game)
            feature = feature_map.get((game_id, entity_id, market))
            if feature is None:
                raise LiveSlateError("feature snapshot missing for quote")
            if engine is None or deployment is None:
                raise LiveSlateError("pitcher BB engine/deployment registration missing")
            candidate = assemble_pitcher_bb_candidate(game=game, feature_row=feature, quote=quote)
            rr = run_candidate(model_input=candidate["model_input"], quote=candidate["quote"], deployment=deployment, engine_fn=engine, ingestion_now=ingestion_now, finalization_now=finalization_now, min_edge=min_edge, kelly_multiplier=kelly_multiplier)
            d = rr.decision
            out.append(PitcherCardResult(
                game_id, market, entity_id, line, side, odds, rr.model_p, rr.bet_status, rr.reason,
                d.implied_probability if d else None,
                d.edge if d else None,
                d.ev_per_dollar if d else None,
                d.kelly_fraction if d else None,
            ))
        except Exception as exc:
            try:
                game_id, market, entity_id, line, side = _identity(raw_quote)
            except Exception:
                game_id, market, entity_id, line, side = "UNKNOWN", "UNKNOWN", "UNKNOWN", None, "UNKNOWN"
            out.append(PitcherCardResult(game_id, market, entity_id, line, side, odds, None, "BLOCKED", f"{type(exc).__name__}: {exc}"))
    return out


def pitcher_card_result_to_dict(result: PitcherCardResult) -> dict[str, Any]:
    return asdict(result)
