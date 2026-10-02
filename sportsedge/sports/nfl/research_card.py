"""NFL research card for sides, totals, team totals, and player props.

Production football prop authority stays NO_ENGINE. This module only combines
already-priced research rows and prices team totals from a market-blind score
distribution that already exists. Missing probabilities stay NO_MODEL.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping, Sequence

from sportsedge.football_prop_extended_run_machine import PROVIDER_MARKETS
from sportsedge.sports.nfl.team_totals import price_nfl_team_totals

SCHEMA_VERSION = "NFL_FULL_RESEARCH_CARD_V1"
GAME_MARKETS = frozenset({"MONEYLINE", "SPREAD", "TOTAL", "TEAM_TOTAL"})
UNSUPPORTED = {
    "first_td": "NO_ENGINE",
    "last_td": "NO_ENGINE",
    "returner_td_identity": "NO_ENGINE",
    "first_half": "NO_ENGINE",
    "second_half": "NO_ENGINE",
    "quarters": "NO_ENGINE",
}


class NFLResearchCardError(ValueError):
    pass


def _probability(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if isfinite(out) and 0.0 <= out <= 1.0 else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if isfinite(out) else None


def _unwrap(payload: Mapping[str, Any], *, code: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise NFLResearchCardError(code)
    nested = payload.get("report")
    return dict(nested) if isinstance(nested, Mapping) else dict(payload)


def _game_row(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    market = str(raw.get("market") or "").strip().upper()
    if market not in GAME_MARKETS:
        return None
    model_p = _probability(raw.get("model_p") if raw.get("model_p") is not None else raw.get("research_p"))
    reason = str(raw.get("reason") or "")
    fresh = "STALE" not in reason.upper()
    lean = model_p is not None and fresh
    return {
        "lane": "SIDE" if market in {"MONEYLINE", "SPREAD"} else "TOTAL",
        "game_id": str(raw.get("game_id") or ""),
        "market": market,
        "side": str(raw.get("side") or ""),
        "selection": raw.get("selection"),
        "line": _number(raw.get("line")),
        "american_odds": _number(raw.get("american_odds")),
        "model_p": model_p,
        "fair_market_p": _probability(raw.get("fair_market_p")),
        "edge": _number(raw.get("edge")),
        "ev_per_dollar": _number(raw.get("ev_per_dollar")),
        "display_status": "LEAN" if lean else "BLOCKED",
        "underlying_bet_status": str(raw.get("bet_status") or "BLOCKED"),
        "official_eligible": False,
        "reason": "NFL_RESEARCH_CARD_GAME_LEAN_OFFICIAL_GATE_UNCHANGED" if lean else (reason or "NFL_RESEARCH_CARD_GAME_BLOCKED"),
        "distribution_sha256": raw.get("distribution_sha256"),
    }


def _prop_row(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    provider_market = str(raw.get("provider_market") or raw.get("market") or "")
    if provider_market not in PROVIDER_MARKETS and str(raw.get("market") or "") not in PROVIDER_MARKETS:
        if str(raw.get("lane") or "").upper() != "PROP":
            return None
    model_p = _probability(raw.get("model_p") if raw.get("model_p") is not None else raw.get("research_p"))
    fresh = raw.get("quote_fresh") is not False and "STALE" not in str(raw.get("reason") or "").upper()
    ready = str(raw.get("model_candidate_status") or "READY").upper() == "READY"
    lean = model_p is not None and fresh and ready
    return {
        "lane": "PROP",
        "game_id": str(raw.get("game_id") or ""),
        "market": str(raw.get("market") or provider_market),
        "provider_market": provider_market,
        "player_id": raw.get("player_id"),
        "player_name": raw.get("player_name"),
        "side": str(raw.get("side") or ""),
        "line": _number(raw.get("line")),
        "american_odds": _number(raw.get("american_odds")),
        "model_p": model_p,
        "fair_market_p": _probability(raw.get("fair_market_p")),
        "edge": _number(raw.get("edge")),
        "ev_per_dollar": _number(raw.get("ev_per_dollar")),
        "display_status": "LEAN" if lean else "NO_MODEL",
        "official_eligible": False,
        "reason": "NFL_RESEARCH_CARD_PROP_LEAN_ENGINE_SURFACE_UNCHANGED" if lean else (str(raw.get("reason") or "NFL_PROP_NO_MODEL")),
        "distribution_sha256": raw.get("distribution_sha256"),
    }


def price_team_total_rows(
    distribution: Sequence[Mapping[str, Any]],
    *,
    game_id: str,
    home_total_line: float,
    away_total_line: float,
    distribution_sha256: str,
) -> list[dict[str, Any]]:
    priced = price_nfl_team_totals(
        distribution,
        home_total_line=home_total_line,
        away_total_line=away_total_line,
    )
    rows = []
    for market, side, line, key in (
        ("TEAM_TOTAL", "HOME", home_total_line, "home_team_total"),
        ("TEAM_TOTAL", "AWAY", away_total_line, "away_team_total"),
    ):
        mass = priced[key]
        rows.append({
            "lane": "TOTAL",
            "game_id": game_id,
            "market": market,
            "side": side,
            "line": float(line),
            "model_p": mass["over"],
            "push_p": mass["push"],
            "under_p": mass["under"],
            "display_status": "LEAN",
            "official_eligible": False,
            "reason": "NFL_TEAM_TOTAL_FROM_EXISTING_SCORE_DISTRIBUTION",
            "distribution_sha256": distribution_sha256,
            "bet_status": "BLOCKED",
        })
    return rows


def assemble_nfl_research_card(
    *,
    game_payload: Mapping[str, Any] | None = None,
    prop_payload: Mapping[str, Any] | None = None,
    team_total_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    game = _unwrap(game_payload or {}, code="NFL_RESEARCH_CARD_GAME_PAYLOAD_INVALID")
    props = _unwrap(prop_payload or {}, code="NFL_RESEARCH_CARD_PROP_PAYLOAD_INVALID")
    game_rows = [row for raw in list(game.get("results") or []) if (row := _game_row(raw))]
    game_rows.extend(_game_row(raw) or {} for raw in list(team_total_rows or []) if _game_row(raw))
    game_rows = [row for row in game_rows if row]
    prop_rows = [row for raw in list(props.get("results") or []) if (row := _prop_row(raw))]
    rows = sorted(
        [*game_rows, *prop_rows],
        key=lambda row: (str(row.get("game_id") or ""), str(row.get("lane") or ""), str(row.get("market") or ""), str(row.get("player_name") or ""), str(row.get("side") or "")),
    )
    leans = [row for row in rows if row["display_status"] == "LEAN"]
    return {
        "schema_version": SCHEMA_VERSION,
        "sport": "NFL",
        "run_status": "RESEARCH_LEANS_AVAILABLE" if leans else "RESEARCH_BLOCKED_NO_LEANS",
        "rows": rows,
        "summary": {
            "side_rows": sum(row["lane"] == "SIDE" for row in rows),
            "total_rows": sum(row["lane"] == "TOTAL" for row in rows),
            "prop_rows": sum(row["lane"] == "PROP" for row in rows),
            "lean_rows": len(leans),
            "official_bets": 0,
            "markets_seen": sorted({str(row["market"]) for row in rows}),
        },
        "unsupported_or_not_promoted": dict(UNSUPPORTED),
        "governance": {
            "research_only": True,
            "production_authority_changed": False,
            "prop_engine_surface_changed": False,
            "truth_gate_changed": False,
            "promotion_authority": False,
            "official_authority": False,
            "staking_authority": False,
        },
    }


__all__ = [
    "GAME_MARKETS",
    "NFLResearchCardError",
    "SCHEMA_VERSION",
    "assemble_nfl_research_card",
    "price_team_total_rows",
]
