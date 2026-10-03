"""Complete football side, total, and prop presentation board.

Game rows and prop rows are presentation inputs. Team totals and period markets
are priced only from an already-built market-blind score distribution. Nothing
here changes the frozen NFL run machine, prop engine surface, Model_P, Truth
Gate, or OFFICIAL authority.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from sportsedge.core.simulate.markets import derive_period_markets
from sportsedge.football_prop_extended_run_machine import PROVIDER_MARKETS
from sportsedge.sports.cfb.team_total_readout import price_cfb_team_total
from sportsedge.sports.nfl.team_totals import price_nfl_team_totals

SCHEMA_VERSION = "FOOTBALL_FULL_BOARD_V2"
DEFAULT_SURFACE = Path("config/football_market_surface.json")
_PACKAGE_ROOT = Path(__file__).resolve().parents[1]

SIDE_MARKETS = frozenset({
    "moneyline", "spread", "first_half_moneyline", "first_half_spread",
    "second_half_moneyline", "second_half_spread", "quarter_moneyline",
    "quarter_spread", "alternate_spread", "race_to_n_points",
})
TOTAL_MARKETS = frozenset({
    "total", "team_total", "first_half_total", "second_half_total",
    "quarter_total", "alternate_total",
})
PROVIDER_TO_SURFACE = {
    "player_pass_attempts": "attempts",
    "player_pass_completions": "completions",
    "player_pass_interceptions": "interceptions",
    "player_pass_longest_completion": "longest_completion",
    "player_pass_rush_yds": "pass_plus_rush_yards",
    "player_pass_tds": "passing_tds",
    "player_pass_yds": "passing_yards",
    "player_receptions": "receptions",
    "player_reception_longest": "longest_reception",
    "player_reception_yds": "receiving_yards",
    "player_rush_attempts": "rush_attempts",
    "player_rush_longest": "longest_rush",
    "player_rush_reception_yds": "rush_plus_rec_yards",
    "player_rush_yds": "rushing_yards",
    "player_anytime_td": "anytime_td",
    "player_field_goals": "fg_made",
    "player_kicking_points": "kicking_points",
    "player_pats": "xp_made",
    "player_sacks": "player_sacks",
    "player_tackles_assists": "tackles_assists",
    "player_defensive_interceptions": "player_interceptions",
}
PERIOD_MARKETS = {
    "first_half_moneyline": ("first_half", "moneyline"),
    "first_half_spread": ("first_half", "spread"),
    "first_half_total": ("first_half", "total"),
    "second_half_moneyline": ("second_half", "moneyline"),
    "second_half_spread": ("second_half", "spread"),
    "second_half_total": ("second_half", "total"),
    "quarter_moneyline": ("quarter", "moneyline"),
    "quarter_spread": ("quarter", "spread"),
    "quarter_total": ("quarter", "total"),
}


class FootballFullBoardError(ValueError):
    pass


def _resolve_surface(surface_path: str | Path = DEFAULT_SURFACE) -> Path:
    path = Path(surface_path)
    if path.is_file():
        return path
    rooted = _PACKAGE_ROOT / path
    if rooted.is_file():
        return rooted
    return path


def surface_markets(surface_path: str | Path = DEFAULT_SURFACE) -> tuple[dict[str, Any], ...]:
    payload = json.loads(_resolve_surface(surface_path).read_text(encoding="utf-8"))
    rows = payload.get("markets")
    if not isinstance(rows, list) or len(rows) < 51:
        raise FootballFullBoardError("FOOTBALL_FULL_BOARD_SURFACE_INCOMPLETE")
    out = []
    seen = set()
    for raw in rows:
        if not isinstance(raw, Mapping) or not str(raw.get("market") or "").strip():
            raise FootballFullBoardError("FOOTBALL_FULL_BOARD_SURFACE_MARKET_INVALID")
        market = str(raw["market"])
        if market in seen:
            raise FootballFullBoardError(f"FOOTBALL_FULL_BOARD_SURFACE_DUPLICATE:{market}")
        seen.add(market)
        out.append({
            "family": str(raw.get("family") or ""),
            "market": market,
            "engine_state_by_sport": dict(raw.get("engine_state_by_sport") or {}),
        })
    return tuple(out)


def _number(value):
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def family_for(market: str, family: str = "") -> str:
    key = str(market or "").strip()
    if key in SIDE_MARKETS or family == "game" and key in SIDE_MARKETS:
        return "SIDE"
    if key in TOTAL_MARKETS:
        return "TOTAL"
    if family == "team_situational":
        return "SITUATIONAL"
    return "PROP"


def _row(
    *,
    sport: str,
    lane: str,
    market: str,
    raw: Mapping[str, Any],
    presentation: str,
    reason: str,
    engine_state: str,
) -> dict[str, Any]:
    model_p = raw.get("model_p")
    return {
        "sport": sport,
        "lane": lane,
        "market": market,
        "family": raw.get("family"),
        "game_id": raw.get("game_id"),
        "entity_id": raw.get("entity_id") or raw.get("player_id") or raw.get("team_side"),
        "selection": raw.get("selection") or raw.get("side") or raw.get("player_name"),
        "line": raw.get("line"),
        "american_odds": raw.get("american_odds") or raw.get("price_american"),
        "model_p": model_p,
        "engine_state": engine_state,
        "research_only": True,
        "official_eligible": False,
        "presentation": presentation,
        "reason": reason,
        "provider_market": raw.get("provider_market"),
    }


def _engine_state(sport: str, spec: Mapping[str, Any] | None) -> str:
    if not spec:
        return "NO_ENGINE"
    return str((spec.get("engine_state_by_sport") or {}).get(sport) or "NO_ENGINE")


def _price_team_totals(
    sport: str,
    distribution: Sequence[Mapping[str, Any]],
    requests: Sequence[Mapping[str, Any]],
    engine_state: str,
) -> list[dict[str, Any]]:
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
            rows.append(_row(
                sport=sport, lane="TOTAL", market="team_total",
                raw={**dict(request), "model_p": priced[key][side.lower()], "family": "game"},
                presentation="LEAN",
                reason="TEAM_TOTAL_DERIVATIVE_NOT_PROMOTION",
                engine_state=engine_state,
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
            sport=sport, lane="TOTAL", market="team_total",
            raw={**dict(request), "model_p": priced[side.lower()], "family": "game"},
            presentation="LEAN",
            reason="TEAM_TOTAL_DERIVATIVE_NOT_PROMOTION",
            engine_state=engine_state,
        ))
    return rows


def _period_name(request: Mapping[str, Any], market: str) -> tuple[str, bool | None]:
    period, _kind = PERIOD_MARKETS[market]
    include_ot = request.get("include_ot")
    if period == "quarter":
        quarter = str(request.get("quarter") or "").strip().lower()
        if quarter not in {"q1", "q2", "q3", "q4", "1", "2", "3", "4"}:
            raise FootballFullBoardError("FOOTBALL_QUARTER_REQUIRED")
        period = quarter if quarter.startswith("q") else f"q{quarter}"
    if period == "second_half" and not isinstance(include_ot, bool):
        raise FootballFullBoardError("SECOND_HALF_OT_RULE_REQUIRED")
    return period, include_ot if isinstance(include_ot, bool) else None


def _price_period(
    sport: str,
    market: str,
    request: Mapping[str, Any],
    distribution: Sequence[Mapping[str, Any]],
    engine_state: str,
) -> dict[str, Any]:
    period, include_ot = _period_name(request, market)
    kind = PERIOD_MARKETS[market][1]
    priced = derive_period_markets(
        distribution,
        period=period,
        spread_line=float(request.get("line") or 0.0),
        total_line=float(request["line"]) if kind == "total" else None,
        include_ot=include_ot,
    )
    side = str(request.get("quoted_side") or request.get("side") or "HOME").upper()
    bucket = priced[{"moneyline": "moneyline", "spread": "spread", "total": "total"}[kind]]
    if kind == "total":
        model_p = bucket[side.lower()]
    elif kind == "spread":
        model_p = bucket["home_cover"] if side == "HOME" else bucket["away_cover"]
    else:
        model_p = bucket["home_win"] if side == "HOME" else bucket["away_win"]
    return _row(
        sport=sport,
        lane=family_for(market),
        market=market,
        raw={**dict(request), "model_p": model_p, "family": "game"},
        presentation="LEAN",
        reason="PERIOD_DERIVATIVE_NOT_PROMOTION",
        engine_state=engine_state,
    )



def _field(raw: Any, name: str) -> Any:
    if isinstance(raw, Mapping):
        return raw.get(name)
    return getattr(raw, name, None)


def board_from_machine_results(
    sport: str,
    results: Sequence[Any],
    *,
    surface: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Presentation board for a football run.

    Priced machine rows stay research rows. Families with no quote or engine row
    stay explicit blockers. This does not price a missing distribution and does
    not grant Model_P, Truth Gate, or OFFICIAL authority.
    """
    specs = tuple(surface) if surface is not None else surface_markets()
    by_market = {str(spec["market"]): spec for spec in specs}
    game_rows: list[dict[str, Any]] = []
    prop_rows: list[dict[str, Any]] = []
    for raw in results:
        market = str(_field(raw, "market") or "").strip()
        key = market.lower()
        if not key or key in {"game", "player_props"}:
            continue
        payload = {
            "market": key,
            "game_id": _field(raw, "game_id"),
            "entity_id": _field(raw, "entity_id") or _field(raw, "player_id"),
            "side": _field(raw, "side") or _field(raw, "selection"),
            "line": _field(raw, "line"),
            "american_odds": _field(raw, "american_odds") or _field(raw, "price_american"),
            "model_p": _field(raw, "model_p"),
            "reason": _field(raw, "reason"),
            "provider_market": _field(raw, "provider_market"),
        }
        spec = by_market.get(key)
        provider = str(payload.get("provider_market") or "")
        if provider or key in PROVIDER_TO_SURFACE or (spec and spec.get("family") not in {"", "game"}):
            prop_rows.append({**payload, "provider_market": provider or key})
            continue
        if key in SIDE_MARKETS or key in TOTAL_MARKETS or spec is not None:
            game_rows.append(payload)
    return build_football_full_board(
        sport=sport,
        game_rows=game_rows,
        prop_rows=prop_rows,
        surface=specs,
    )


def build_football_full_board(
    *,
    sport: str,
    game_rows: Sequence[Mapping[str, Any]] = (),
    prop_rows: Sequence[Mapping[str, Any]] = (),
    team_total_requests: Sequence[Mapping[str, Any]] = (),
    period_requests: Sequence[Mapping[str, Any]] = (),
    distribution: Sequence[Mapping[str, Any]] | None = None,
    surface: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved = str(sport or "").strip().upper()
    if resolved not in {"NFL", "CFB"}:
        raise FootballFullBoardError(f"FOOTBALL_FULL_BOARD_SPORT_UNSUPPORTED:{sport}")
    specs = tuple(surface) if surface is not None else surface_markets()
    by_market = {str(spec["market"]): spec for spec in specs}
    emitted: list[dict[str, Any]] = []
    seen: set[str] = set()

    def remember(market: str) -> None:
        seen.add(market)
        mapped = PROVIDER_TO_SURFACE.get(market)
        if mapped:
            seen.add(mapped)

    for raw in game_rows:
        market = str(raw.get("market") or "").strip()
        key = market.lower()
        if key not in by_market and key not in SIDE_MARKETS | TOTAL_MARKETS:
            raise FootballFullBoardError(f"FOOTBALL_FULL_BOARD_GAME_MARKET_UNSUPPORTED:{market}")
        remember(key)
        model_p = raw.get("model_p")
        spec = by_market.get(key)
        emitted.append(_row(
            sport=resolved,
            lane=family_for(key, str((spec or {}).get("family") or "game")),
            market=key,
            raw={**dict(raw), "family": (spec or {}).get("family", "game")},
            presentation="LEAN" if model_p is not None else "NO_MODEL",
            reason=str(raw.get("reason") or "GAME_RESEARCH_ROW"),
            engine_state=_engine_state(resolved, spec),
        ))

    if team_total_requests:
        spec = by_market.get("team_total")
        engine_state = _engine_state(resolved, spec)
        remember("team_total")
        if not distribution:
            for request in team_total_requests:
                emitted.append(_row(
                    sport=resolved, lane="TOTAL", market="team_total",
                    raw={**dict(request), "family": "game"},
                    presentation="NO_MODEL",
                    reason="TEAM_TOTAL_DISTRIBUTION_REQUIRED",
                    engine_state=engine_state,
                ))
        else:
            emitted.extend(_price_team_totals(resolved, distribution, team_total_requests, engine_state))

    for request in period_requests:
        market = str(request.get("market") or "").strip().lower()
        if market not in PERIOD_MARKETS:
            raise FootballFullBoardError(f"FOOTBALL_FULL_BOARD_PERIOD_MARKET_UNSUPPORTED:{market}")
        spec = by_market.get(market)
        engine_state = _engine_state(resolved, spec)
        remember(market)
        if not distribution:
            emitted.append(_row(
                sport=resolved, lane=family_for(market), market=market,
                raw={**dict(request), "family": "game"},
                presentation="NO_MODEL",
                reason="PERIOD_DISTRIBUTION_REQUIRED",
                engine_state=engine_state,
            ))
            continue
        try:
            emitted.append(_price_period(resolved, market, request, distribution, engine_state))
        except (FootballFullBoardError, ValueError) as exc:
            emitted.append(_row(
                sport=resolved, lane=family_for(market), market=market,
                raw={**dict(request), "family": "game"},
                presentation="NO_MODEL",
                reason=str(exc),
                engine_state=engine_state,
            ))

    for raw in prop_rows:
        provider = str(raw.get("provider_market") or raw.get("market") or "").strip()
        if not provider:
            raise FootballFullBoardError("FOOTBALL_FULL_BOARD_PROP_MARKET_REQUIRED")
        market = PROVIDER_TO_SURFACE.get(provider, provider)
        remember(provider)
        spec = by_market.get(market)
        emitted.append(_row(
            sport=resolved,
            lane="PROP",
            market=market,
            raw={**dict(raw), "provider_market": provider, "family": (spec or {}).get("family", "prop")},
            presentation="LEAN" if raw.get("model_p") is not None else "NO_MODEL",
            reason=str(raw.get("reason") or "PROP_RESEARCH_ROW_NO_ENGINE_AUTHORITY"),
            engine_state=_engine_state(resolved, spec),
        ))

    for spec in specs:
        market = str(spec["market"])
        if market in seen:
            continue
        engine_state = _engine_state(resolved, spec)
        emitted.append(_row(
            sport=resolved,
            lane=family_for(market, str(spec.get("family") or "")),
            market=market,
            raw={"family": spec.get("family")},
            presentation="BLOCKED",
            reason="NO_ENGINE" if engine_state == "NO_ENGINE" else "NO_QUOTE_OR_ENGINE_ROW",
            engine_state=engine_state,
        ))
    for market in sorted(PROVIDER_MARKETS):
        if market in seen or PROVIDER_TO_SURFACE.get(market) in seen:
            continue
        emitted.append(_row(
            sport=resolved, lane="PROP", market=market, raw={"provider_market": market, "family": "prop"},
            presentation="BLOCKED", reason="NO_QUOTE_OR_ENGINE_ROW", engine_state="NO_ENGINE",
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
            "surface_markets": len(specs),
            "side_rows": sum(1 for row in emitted if row["lane"] == "SIDE"),
            "total_rows": sum(1 for row in emitted if row["lane"] == "TOTAL"),
            "prop_rows": sum(1 for row in emitted if row["lane"] == "PROP"),
            "situational_rows": sum(1 for row in emitted if row["lane"] == "SITUATIONAL"),
            "priced_rows": sum(1 for row in emitted if row["model_p"] is not None),
            "official_bets": 0,
        },
        "all_props_side_totals": emit_all_props_side_totals(
            sport=resolved, game_rows=game_rows, prop_rows=prop_rows,
        ),
        "rows": emitted,
    }


def emit_all_props_side_totals(
    *,
    sport: str,
    game_rows: Sequence[Mapping[str, Any]] | None = None,
    prop_rows: Sequence[Mapping[str, Any]] | None = None,
    surface_path: str | Path = DEFAULT_SURFACE,
) -> dict[str, Any]:
    """Emit both sides of every football side, total, and prop on the board.

    Quoted rows keep their probability. Missing complements stay explicit.
    Surface markets with no quote stay blockers. No official authority.
    """
    resolved = str(sport or "").strip().upper()
    if resolved not in {"NFL", "CFB"}:
        raise FootballFullBoardError(f"FOOTBALL_SPORT_UNSUPPORTED:{sport}")
    specs = surface_markets(surface_path)
    by_market = {str(spec["market"]): spec for spec in specs}
    pairs = {
        "moneyline": ("HOME", "AWAY"),
        "spread": ("HOME", "AWAY"),
        "first_half_moneyline": ("HOME", "AWAY"),
        "first_half_spread": ("HOME", "AWAY"),
        "second_half_moneyline": ("HOME", "AWAY"),
        "second_half_spread": ("HOME", "AWAY"),
        "quarter_moneyline": ("HOME", "AWAY"),
        "quarter_spread": ("HOME", "AWAY"),
        "alternate_spread": ("HOME", "AWAY"),
        "total": ("OVER", "UNDER"),
        "team_total": ("OVER", "UNDER"),
        "first_half_total": ("OVER", "UNDER"),
        "second_half_total": ("OVER", "UNDER"),
        "quarter_total": ("OVER", "UNDER"),
        "alternate_total": ("OVER", "UNDER"),
    }
    grouped: dict[tuple[str, str, str, str], dict[str, Mapping[str, Any]]] = {}
    order: list[tuple[str, str, str, str]] = []
    for raw in list(game_rows or []) + list(prop_rows or []):
        if not isinstance(raw, Mapping):
            raise FootballFullBoardError("FOOTBALL_ALL_SIDES_ROW_INVALID")
        market = str(raw.get("market") or raw.get("provider_market") or "").strip()
        if not market or market.upper() in {"GAME", "PLAYER_PROPS", "UNKNOWN"}:
            continue
        market = PROVIDER_TO_SURFACE.get(market, market)
        key = (
            market,
            str(raw.get("game_id") or ""),
            str(raw.get("entity_id") or raw.get("player") or raw.get("team_side") or ""),
            "" if raw.get("line") is None else str(raw.get("line")),
        )
        side = str(raw.get("side") or raw.get("quoted_side") or "").strip().upper()
        if not side:
            side = "HOME" if market in {"moneyline", "spread", "first_half_moneyline", "first_half_spread", "second_half_moneyline", "second_half_spread", "quarter_moneyline", "quarter_spread", "alternate_spread"} else "OVER"
        if key not in grouped:
            grouped[key] = {}
            order.append(key)
        grouped[key][side] = raw
    emitted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in order:
        market = key[0]
        seen.add(market)
        present = grouped[key]
        left, right = pairs.get(market, ("OVER", "UNDER"))
        spec = by_market.get(market)
        lane = family_for(market, str((spec or {}).get("family") or ""))
        for side in (left, right):
            raw = present.get(side)
            if raw is None:
                donor = next(iter(present.values()))
                model_p = _number(donor.get("model_p"))
                emitted.append(_row(
                    sport=resolved, lane=lane, market=market,
                    raw={**dict(donor), "side": side, "model_p": None if model_p is None else max(0.0, 1.0 - model_p), "american_odds": donor.get("opposite_odds")},
                    presentation="COMPLEMENT" if donor.get("opposite_odds") is not None else "NO_QUOTE",
                    reason="COMPLEMENT_SIDE_NOT_QUOTED",
                    engine_state=_engine_state(resolved, spec),
                ))
                continue
            model_p = _number(raw.get("model_p"))
            emitted.append(_row(
                sport=resolved, lane=lane, market=market,
                raw={**dict(raw), "side": side, "model_p": model_p},
                presentation="LEAN" if model_p is not None else "NO_MODEL",
                reason=str(raw.get("reason") or "RESEARCH_ROW"),
                engine_state=_engine_state(resolved, spec),
            ))
    for spec in specs:
        market = str(spec["market"])
        if market in seen:
            continue
        left, right = pairs.get(market, ("OVER", "UNDER"))
        for side in (left, right):
            emitted.append(_row(
                sport=resolved, lane=family_for(market, str(spec.get("family") or "")), market=market,
                raw={"family": spec.get("family"), "side": side},
                presentation="BLOCKED",
                reason="NO_ENGINE" if _engine_state(resolved, spec) == "NO_ENGINE" else "NO_QUOTE_OR_ENGINE_ROW",
                engine_state=_engine_state(resolved, spec),
            ))
    return {
        "schema_version": "FOOTBALL_ALL_PROPS_SIDE_TOTALS_V1",
        "sport": resolved,
        "authority": "PRESENTATION_ONLY",
        "prop_engine_state": "NO_ENGINE",
        "model_p_authority": False,
        "truth_gate_authority": False,
        "official_authority": False,
        "summary": {
            "surface_markets": len(specs),
            "quoted_groups": len(order),
            "side_rows": sum(1 for row in emitted if row["lane"] == "SIDE"),
            "total_rows": sum(1 for row in emitted if row["lane"] == "TOTAL"),
            "prop_rows": sum(1 for row in emitted if row["lane"] == "PROP"),
            "official_bets": 0,
        },
        "rows": emitted,
    }
