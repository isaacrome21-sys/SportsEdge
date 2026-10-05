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

SCHEMA_VERSION = "FOOTBALL_FULL_BOARD_V3"
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
    "player_reception_tds": "receiving_tds",
    "player_reception_yds": "receiving_yards",
    "player_rush_attempts": "rush_attempts",
    "player_rush_tds": "rushing_tds",
    "player_rush_reception_tds": "rush_rec_tds",
    "player_solo_tackles": "solo_tackles",
    "player_tds_over": "tds_over",
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
    "player_targets": "targets",
    "player_reception_targets": "targets",
    "player_first_td": "first_td",
    "player_1st_td": "first_td",
    "player_two_plus_td": "two_plus_td",
    "player_2plus_tds": "two_plus_td",
    "player_qb_rush_yds": "rush_yards",
    "team_sacks": "team_sacks",
    "team_turnovers": "team_turnovers",
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
        "team_side": raw.get("team_side"),
        "selection": raw.get("selection") or raw.get("side") or raw.get("quoted_side") or raw.get("player_name"),
        "line": raw.get("line"),
        "opposite_odds": raw.get("opposite_odds"),
        "american_odds": raw.get("american_odds") or raw.get("price_american"),
        "model_p": model_p,
        "push_p": raw.get("push_p"),
        "tie_p": raw.get("tie_p"),
        "complement_model_p": raw.get("complement_model_p"),
        "opposite_model_p": raw.get("opposite_model_p"),
        "count_pmf": raw.get("count_pmf"),
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
                raw={**dict(request), "side": side, "model_p": priced[key][side.lower()], "family": "game"},
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
            raw={**dict(request), "side": side, "model_p": priced[side.lower()], "family": "game"},
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
        raw={**dict(request), "side": side, "model_p": model_p, "family": "game"},
        presentation="LEAN",
        reason="PERIOD_DERIVATIVE_NOT_PROMOTION",
        engine_state=engine_state,
    )



def _field(raw: Any, name: str) -> Any:
    if isinstance(raw, Mapping):
        return raw.get(name)
    return getattr(raw, name, None)



def pair_sides(market: str, lane: str = "") -> tuple[str, str]:
    key = str(market or "").strip().lower()
    if key in SIDE_MARKETS or lane == "SIDE":
        return ("HOME", "AWAY")
    if key in {"anytime_td", "player_anytime_td"} or lane == "SITUATIONAL":
        return ("YES", "NO")
    return ("OVER", "UNDER")


def _selection(row: Mapping[str, Any]) -> str:
    return str(row.get("selection") or row.get("side") or "").strip().upper()


def _with_complements(sport: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append the unquoted side. Price it only from a supplied opposite quote."""
    from sportsedge.both_side_pricing import complement_model_p

    from sportsedge.both_side_pricing import attach_sibling_quotes

    def identity(row):
        line = row.get("line")
        if str(row.get("market") or "").endswith("spread") and _selection(row) == "AWAY" and line is not None:
            line = -float(line)
        return (
            row.get("market"),
            row.get("game_id"),
            row.get("entity_id"),
            row.get("team_side"),
            line,
            row.get("provider_market"),
        )

    rows = attach_sibling_quotes(
        rows,
        group_key=identity,
        side_of=_selection,
    )
    grouped: dict[tuple[Any, ...], set[str]] = {}
    templates: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = identity(row)
        grouped.setdefault(key, set()).add(_selection(row))
        templates.setdefault(key, row)
    extra: list[dict[str, Any]] = []
    for key, present in grouped.items():
        template = templates[key]
        left, right = pair_sides(str(template.get("market") or ""), str(template.get("lane") or ""))
        for side in (left, right):
            if side in present:
                continue
            opposite = template.get("opposite_odds")
            model_p = complement_model_p(template, market=str(template.get("market") or "")) if opposite is not None else None
            if opposite is None:
                reason = "COMPLEMENT_SIDE_NOT_QUOTED"
                presentation = "BLOCKED"
            elif model_p is None:
                reason = "COMPLEMENT_PRICE_ONLY"
                presentation = "BLOCKED"
            else:
                reason = "COMPLEMENT_PRICED_FROM_QUOTED_SIDE"
                presentation = "LEAN"
            complement = dict(template)
            complement["selection"] = side
            complement["side"] = side
            if str(template.get("market") or "").endswith("spread") and template.get("line") is not None:
                complement["line"] = -float(template["line"])
            complement["model_p"] = model_p
            complement["american_odds"] = opposite
            complement["presentation"] = presentation
            complement["reason"] = reason
            complement["research_only"] = True
            complement["official_eligible"] = False
            extra.append(complement)
            present.add(side)
    return rows + extra


def catalog_complete(summary: Mapping[str, Any]) -> bool:
    """True only when every surface and provider family has both sides."""
    return (
        summary.get("both_sides") is True
        and int(summary.get("side_rows") or 0) >= 16
        and int(summary.get("total_rows") or 0) >= 10
        and int(summary.get("prop_rows") or 0) >= 40
    )


def emit_all_props_side_totals(**kwargs: Any) -> dict[str, Any]:
    return build_football_full_board(**kwargs)


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
            "team_side": _field(raw, "team_side"),
            "side": _field(raw, "side") or _field(raw, "selection"),
            "line": _field(raw, "line"),
            "american_odds": _field(raw, "american_odds") or _field(raw, "price_american"),
            "opposite_odds": _field(raw, "opposite_odds"),
            "model_p": _field(raw, "model_p"),
            "push_p": _field(raw, "push_p"),
            "tie_p": _field(raw, "tie_p"),
            "complement_model_p": _field(raw, "complement_model_p"),
            "opposite_model_p": _field(raw, "opposite_model_p"),
            "count_pmf": _field(raw, "count_pmf"),
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
        lane = family_for(market, str(spec.get("family") or ""))
        reason = "NO_ENGINE" if engine_state == "NO_ENGINE" else "NO_QUOTE_OR_ENGINE_ROW"
        team_sides = ("HOME", "AWAY") if market == "team_total" else (None,)
        for team_side in team_sides:
            for side in pair_sides(market, lane):
                raw = {"family": spec.get("family"), "side": side}
                if team_side:
                    raw["team_side"] = team_side
                emitted.append(_row(
                    sport=resolved,
                    lane=lane,
                    market=market,
                    raw=raw,
                    presentation="BLOCKED",
                    reason=reason,
                    engine_state=engine_state,
                ))
    for market in sorted(PROVIDER_MARKETS):
        mapped = PROVIDER_TO_SURFACE.get(market, market)
        if market in seen or mapped in seen:
            continue
        for side in pair_sides(mapped, "PROP"):
            emitted.append(_row(
                sport=resolved, lane="PROP", market=mapped,
                raw={"provider_market": market, "family": "prop", "side": side},
                presentation="BLOCKED", reason="NO_QUOTE_OR_ENGINE_ROW", engine_state="NO_ENGINE",
            ))
            seen.add(mapped)
    emitted = _with_complements(resolved, emitted)
    if any(row.get("market") == "team_total" for row in emitted):
        present = {str(row.get("team_side") or "") for row in emitted if row.get("market") == "team_total"}
        spec = by_market.get("team_total")
        engine_state = _engine_state(resolved, spec)
        for team_side in ("HOME", "AWAY"):
            if team_side in present:
                continue
            for side in pair_sides("team_total", "TOTAL"):
                emitted.append(_row(
                    sport=resolved, lane="TOTAL", market="team_total",
                    raw={"family": "game", "team_side": team_side, "side": side},
                    presentation="BLOCKED", reason="NO_QUOTE_OR_ENGINE_ROW", engine_state=engine_state,
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
            "both_sides": all(
                {str(row.get("selection") or "") for row in emitted if row["market"] == spec["market"]} >= set(pair_sides(str(spec["market"]), family_for(str(spec["market"]), str(spec.get("family") or ""))))
                and (
                    spec["market"] != "team_total"
                    or {str(row.get("team_side") or "") for row in emitted if row["market"] == "team_total"} >= {"HOME", "AWAY"}
                )
                for spec in specs
            ) and all(
                {str(row.get("selection") or "") for row in emitted if row["market"] == PROVIDER_TO_SURFACE.get(market, market)} >= set(pair_sides(PROVIDER_TO_SURFACE.get(market, market), "PROP"))
                for market in PROVIDER_MARKETS
            ),
            "priced_complement_rows": sum(1 for row in emitted if row.get("reason") == "COMPLEMENT_PRICED_FROM_QUOTED_SIDE"),
            "official_bets": 0,
        },
        "rows": emitted,
    }
