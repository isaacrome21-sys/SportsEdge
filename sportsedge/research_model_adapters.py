"""Thin adapters that turn existing engines into bridge-compatible research rows.

These do not create new predictive models. They call (or accept outputs from)
the existing MLB pitcher joint engine, football player-stat path markets, and
free game projections, then emit the exact schema required by
research_three_sport_bridge.price_three_sport_research.

Missing inputs, engine failures, and non-market-blind sources fail closed.
No odds, Model_P, Official, or staking authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .pitcher_joint_engine import PitcherJointEngineError, price_pitcher_market
from .core.simulate.player_markets import derive_player_stat_market


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _require_str(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name}_REQUIRED")
    return text


def _bridge_row(
    *,
    sport: str,
    game_id: str,
    market: str,
    selection: str,
    estimate_p: float,
    push_p: float = 0.0,
    model_source: str,
    as_of: datetime,
    kickoff_utc: str,
    phase: str = "PREGAME",
    player_id: str | None = None,
    line: float | None = None,
    home_team: str | None = None,
    away_team: str | None = None,
    live_state: Mapping[str, Any] | None = None,
    live_model: bool = False,
) -> dict[str, Any]:
    """Build one market-blind PRICED_RESEARCH row the bridge will accept."""
    if not 0 <= estimate_p <= 1 or not 0 <= push_p < 1 or estimate_p + push_p > 1 + 1e-9:
        raise ValueError("MODEL_MASS_INVALID")
    row: dict[str, Any] = {
        "sport": sport.upper(),
        "game_id": _require_str(game_id, "GAME_ID"),
        "market": market.upper(),
        "selection": selection.upper(),
        "status": "PRICED_RESEARCH",
        "market_blind": True,
        "model_source": _require_str(model_source, "MODEL_SOURCE"),
        "estimate_p": float(estimate_p),
        "push_p": float(push_p),
        "as_of_utc": as_of.astimezone(timezone.utc).isoformat(),
        "kickoff_utc": _require_str(kickoff_utc, "KICKOFF"),
        "phase": phase.upper(),
        "validated_vs_close": False,
        "official_authority": False,
    }
    if player_id:
        row["player_id"] = _require_str(player_id, "PLAYER_ID")
    if line is not None:
        row["line"] = float(line)
    if home_team:
        row["home_team"] = home_team
    if away_team:
        row["away_team"] = away_team
    if phase.upper() == "LIVE":
        if not live_model or not isinstance(live_state, Mapping):
            raise ValueError("VERIFIED_LIVE_MODEL_STATE_REQUIRED")
        required = ("period", "clock", "home_score", "away_score")
        if not all(live_state.get(k) is not None for k in required) or not live_state.get("verified_source"):
            raise ValueError("VERIFIED_LIVE_MODEL_STATE_REQUIRED")
        row["live_model"] = True
        row["live_state"] = dict(live_state)
    return row


def mlb_pitcher_to_bridge_rows(
    *,
    game_id: str,
    player_id: str,
    market: str,
    side: str,
    line: float,
    features: Mapping[str, Any],
    kickoff_utc: str,
    as_of: datetime | None = None,
    home_team: str | None = None,
    away_team: str | None = None,
    model_source: str = "mlb_pitcher_joint_engine",
) -> list[dict[str, Any]]:
    """Call the existing pitcher joint engine and emit one bridge row.

    Fails closed if the engine cannot price from strictly prior history.
    """
    as_of = as_of or _now_utc()
    try:
        result = price_pitcher_market({
            "market": market,
            "side": side,
            "line": line,
            "features": features,
        })
        p = float(result.get("p") or result.get("estimate_p") or 0)
        push = float(result.get("p_push") or result.get("push_p") or 0)
        if p <= 0 or p >= 1:
            raise ValueError("ENGINE_RETURNED_INVALID_PROBABILITY")
        return [_bridge_row(
            sport="MLB",
            game_id=game_id,
            market=market,
            selection=side,
            estimate_p=p,
            push_p=push,
            model_source=model_source,
            as_of=as_of,
            kickoff_utc=kickoff_utc,
            player_id=player_id,
            line=line,
            home_team=home_team,
            away_team=away_team,
        )]
    except (PitcherJointEngineError, ValueError, KeyError, TypeError) as exc:
        return [{
            "sport": "MLB",
            "game_id": game_id,
            "market": market,
            "selection": side,
            "player_id": player_id,
            "status": "NO_MODEL_OR_MARKET",
            "reason": str(exc)[:150],
            "research_only": True,
        }]


def football_player_stat_to_bridge_rows(
    *,
    sport: str,
    game_id: str,
    player_id: str,
    stat: str,
    line: float,
    side: str,
    paths: Sequence[Any],
    kickoff_utc: str,
    as_of: datetime | None = None,
    home_team: str | None = None,
    away_team: str | None = None,
    model_source: str | None = None,
) -> list[dict[str, Any]]:
    """Call derive_player_stat_market on existing attributed paths and emit a bridge row.

    Works for both NFL and CFB when the shared football simulation has produced paths.
    """
    as_of = as_of or _now_utc()
    sport = sport.upper()
    if sport not in {"NFL", "CFB"}:
        raise ValueError("SPORT_MUST_BE_NFL_OR_CFB")
    source = model_source or f"{sport.lower()}_player_stat_paths"
    try:
        masses = derive_player_stat_market(
            paths,
            player_id=player_id,
            stat=stat,
            line=line,
        )
        p = float(masses["over"] if side.upper() == "OVER" else masses["under"])
        push = float(masses.get("push", 0))
        market_name = f"PLAYER_{stat.upper()}"
        return [_bridge_row(
            sport=sport,
            game_id=game_id,
            market=market_name,
            selection=side,
            estimate_p=p,
            push_p=push,
            model_source=source,
            as_of=as_of,
            kickoff_utc=kickoff_utc,
            player_id=player_id,
            line=line,
            home_team=home_team,
            away_team=away_team,
        )]
    except (ValueError, TypeError, KeyError) as exc:
        return [{
            "sport": sport,
            "game_id": game_id,
            "market": f"PLAYER_{stat.upper()}",
            "selection": side,
            "player_id": player_id,
            "status": "NO_MODEL_OR_MARKET",
            "reason": str(exc)[:150],
            "research_only": True,
        }]


def free_game_projection_to_bridge_rows(
    *,
    sport: str,
    game_id: str,
    market: str,
    side: str,
    estimate_p: float,
    push_p: float = 0.0,
    kickoff_utc: str,
    line: float | None = None,
    as_of: datetime | None = None,
    home_team: str | None = None,
    away_team: str | None = None,
    model_source: str = "free_independent_score_heuristic",
) -> list[dict[str, Any]]:
    """Convert an already-computed free independent game projection into a bridge row.

    The free model remains market-blind; this only formats it for the bridge.
    """
    as_of = as_of or _now_utc()
    try:
        return [_bridge_row(
            sport=sport,
            game_id=game_id,
            market=market,
            selection=side,
            estimate_p=estimate_p,
            push_p=push_p,
            model_source=model_source,
            as_of=as_of,
            kickoff_utc=kickoff_utc,
            line=line,
            home_team=home_team,
            away_team=away_team,
        )]
    except ValueError as exc:
        return [{
            "sport": sport.upper(),
            "game_id": game_id,
            "market": market,
            "selection": side,
            "status": "NO_MODEL_OR_MARKET",
            "reason": str(exc)[:150],
            "research_only": True,
        }]
