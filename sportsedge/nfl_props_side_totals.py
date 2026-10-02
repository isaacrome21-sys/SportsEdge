"""Research readout for NFL sides, totals, team totals, and prop intake.

Attempt-9 still owns the phone pick. This module does not emit Model_P and
does not promote discrete v2. Props without a role bundle stay NO_MODEL.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from sportsedge.sports.nfl.discrete_v2 import means_from_attempt9, score_grid
from sportsedge.sports.nfl.unified_market_engine import price_game_market

GAME_MARKETS = frozenset({"moneyline", "spread", "total", "team_total"})
AUTHORITY = "RESEARCH_READOUT_NOT_OFFICIAL"
NO_ROLE = "NO_MODEL:ROLE_BUNDLE_REQUIRED"


def research_game_readout(
    forecast: Mapping[str, Any],
    markets: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Price pasted sides/totals/team totals from the frozen score grid."""
    margin = forecast.get("margin")
    total = forecast.get("total")
    if margin is None or total is None:
        return []
    means = means_from_attempt9(float(margin), float(total))
    grid = score_grid(means["mean_home"], means["mean_away"])
    rows: list[dict[str, Any]] = []
    for raw in markets:
        market = str(raw.get("market") or "")
        if market not in GAME_MARKETS:
            rows.append({
                "market": market,
                "subject": raw.get("subject"),
                "no_model": NO_ROLE,
                "authority": AUTHORITY,
            })
            continue
        line = raw.get("line")
        team_side = str(raw.get("team_side") or "").lower() or None
        priced = []
        if market == "moneyline":
            selections = ("away", "home")
        elif market == "spread":
            selections = ("away", "home")
        else:
            selections = ("over", "under")
        for selection in selections:
            request = {"market": market, "selection": selection}
            if line is not None:
                request["line"] = -float(line) if market == "spread" and selection == "home" else float(line)
            if market == "team_total":
                request["team"] = team_side
            result = price_game_market(grid, request)
            priced.append({
                "selection": selection,
                "line": request.get("line"),
                "model_p": float(result["estimate_p"]),
                "push_p": float(result.get("push_p") or 0.0),
            })
        rows.append({
            "market": market,
            "team_side": team_side,
            "subject": raw.get("subject"),
            "sides": priced,
            "no_model": None,
            "authority": AUTHORITY,
        })
    return rows
