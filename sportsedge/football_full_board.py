"""Complete football side, total, and prop presentation board.

Game rows and prop rows are presentation inputs. Team totals are priced only
from an already-built market-blind score distribution via the existing readout.
Nothing here changes the frozen NFL run machine, prop engine surface, Model_P,
Truth Gate, or OFFICIAL authority.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from sportsedge.football_prop_extended_run_machine import PROVIDER_MARKETS
from sportsedge.sports.cfb.team_total_readout import price_cfb_team_total
from sportsedge.sports.nfl.team_totals import price_nfl_team_totals

SCHEMA_VERSION = "FOOTBALL_FULL_BOARD_V1"
SIDE_MARKETS = frozenset({"MONEYLINE", "SPREAD"})
TOTAL_MARKETS = frozenset({"TOTAL", "TEAM_TOTAL"})


class FootballFullBoardError(ValueError):
    pass


def _family(market: str) -> str:
    key = market.upper()
    if key in SIDE_MARKETS:
        return "SIDE"
    if key in TOTAL_MARKETS:
        return "TOTAL"
    return "PLAYER_PROP"


def _row(*, sport: str, lane: str, market: str, raw: Mapping[str, Any], presentation: str, reason: str) -> dict[str, Any]:
    return {
        "sport": sport,
        "lane": lane,
        "market": market,
        "game_id": raw.get("game_id"),
        "entity_id": raw.get("entity_id") or raw.get("player_id") or raw.get("team_side"),
        "selection": raw.get("selection") or raw.get("side") or raw.get("player_name"),
        "line": raw.get("line"),
        "american_odds": raw.get("american_odds"),
        "model_p": raw.get("model_p"),
        "research_only": True,
        "official_eligible": False,
        "presentation": presentation,
        "reason": reason,
    }


def _price_team_totals(sport: str, distribution: Sequence[Mapping[str, Any]], requests: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if sport == "NFL":
        home = next((row for row in requests if str(row.get("team_side") or "").upper() == "HOME"), None)
        away = next((row for row in requests if str(row.get("team_side") or "").upper() == "AWAY"), None)
        if home is None or away is None:
            raise FootballFullBoardError("NFL_TEAM_TOTAL_BOTH_SIDES_REQUIRED")
        priced = price_nfl_team_totals(
            distribution,
            home_total_line=float(home["line"]),
            away_total_line=float(away["line"]),
        )
        for request, key in ((home, "home_team_total"), (away, "away_team_total")):
            side = str(request.get("quoted_side") or "OVER").upper()
            probs = priced[key]
            rows.append(_row(
                sport=sport, lane="TOTAL", market="TEAM_TOTAL",
                raw={**dict(request), "model_p": probs[side.lower()]},
                presentation="LEAN",
                reason="TEAM_TOTAL_DERIVATIVE_NOT_PROMOTION",
            ))
        return rows
    for request in requests:
        priced = price_cfb_team_total(
            distribution,
            team_side=str(request["team_side"]),
            line=float(request["line"]),
        )
        side = str(request.get("quoted_side") or "OVER").upper()
        rows.append(_row(
            sport=sport, lane="TOTAL", market="TEAM_TOTAL",
            raw={**dict(request), "model_p": priced[side.lower()]},
            presentation="LEAN",
            reason="TEAM_TOTAL_DERIVATIVE_NOT_PROMOTION",
        ))
    return rows


def build_football_full_board(
    *,
    sport: str,
    game_rows: Sequence[Mapping[str, Any]] = (),
    prop_rows: Sequence[Mapping[str, Any]] = (),
    team_total_requests: Sequence[Mapping[str, Any]] = (),
    distribution: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved = str(sport or "").strip().upper()
    if resolved not in {"NFL", "CFB"}:
        raise FootballFullBoardError(f"FOOTBALL_FULL_BOARD_SPORT_UNSUPPORTED:{sport}")
    emitted: list[dict[str, Any]] = []
    seen_game: set[str] = set()
    for raw in game_rows:
        market = str(raw.get("market") or "").upper()
        if market not in SIDE_MARKETS | TOTAL_MARKETS:
            raise FootballFullBoardError(f"FOOTBALL_FULL_BOARD_GAME_MARKET_UNSUPPORTED:{market}")
        seen_game.add(market)
        model_p = raw.get("model_p")
        emitted.append(_row(
            sport=resolved, lane=_family(market), market=market, raw=raw,
            presentation="LEAN" if model_p is not None else "NO_MODEL",
            reason=str(raw.get("reason") or "GAME_RESEARCH_ROW"),
        ))
    for market in ("MONEYLINE", "SPREAD", "TOTAL"):
        if market in seen_game:
            continue
        emitted.append(_row(
            sport=resolved, lane=_family(market), market=market, raw={},
            presentation="BLOCKED", reason="NO_QUOTE_OR_ENGINE_ROW",
        ))
    if team_total_requests:
        if not distribution:
            for request in team_total_requests:
                emitted.append(_row(
                    sport=resolved, lane="TOTAL", market="TEAM_TOTAL", raw=request,
                    presentation="NO_MODEL", reason="TEAM_TOTAL_DISTRIBUTION_REQUIRED",
                ))
        else:
            emitted.extend(_price_team_totals(resolved, distribution, team_total_requests))
    elif "TEAM_TOTAL" not in seen_game:
        emitted.append(_row(
            sport=resolved, lane="TOTAL", market="TEAM_TOTAL", raw={},
            presentation="BLOCKED", reason="NO_QUOTE_OR_ENGINE_ROW",
        ))
    seen_props: set[str] = set()
    for raw in prop_rows:
        market = str(raw.get("provider_market") or raw.get("market") or "").strip()
        if not market:
            raise FootballFullBoardError("FOOTBALL_FULL_BOARD_PROP_MARKET_REQUIRED")
        seen_props.add(market)
        emitted.append(_row(
            sport=resolved, lane="PLAYER_PROP", market=market, raw=raw,
            presentation="LEAN" if raw.get("model_p") is not None else "NO_MODEL",
            reason=str(raw.get("reason") or "PROP_RESEARCH_ROW_NO_ENGINE_AUTHORITY"),
        ))
    for market in sorted(PROVIDER_MARKETS):
        if market in seen_props:
            continue
        emitted.append(_row(
            sport=resolved, lane="PLAYER_PROP", market=market, raw={},
            presentation="BLOCKED", reason="NO_QUOTE_OR_ENGINE_ROW",
        ))
    return {
        "schema_version": SCHEMA_VERSION,
        "sport": resolved,
        "authority": "PRESENTATION_ONLY",
        "prop_engine_state": "NO_ENGINE",
        "model_p_authority": False,
        "truth_gate_authority": False,
        "official_authority": False,
        "summary": {
            "side_rows": sum(1 for row in emitted if row["lane"] == "SIDE"),
            "total_rows": sum(1 for row in emitted if row["lane"] == "TOTAL"),
            "prop_rows": sum(1 for row in emitted if row["lane"] == "PLAYER_PROP"),
            "priced_rows": sum(1 for row in emitted if row["model_p"] is not None),
            "official_bets": 0,
        },
        "rows": emitted,
    }
