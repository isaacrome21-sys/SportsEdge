"""Explicit market-family coverage accounting for every Full Model run.

A market family may be actionable, blocked, acquired without a live model, or not
found. It may never silently disappear from the run evidence.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping

REQUIRED_MARKET_FAMILIES = (
    "MONEYLINE", "RUN_LINE", "TOTALS",
    "F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS",
    "NRFI_YRFI",
    "PITCHER_K", "PITCHER_OUTS", "PITCHER_HITS", "PITCHER_BB", "PITCHER_ER",
    "HITS", "TOTAL_BASES", "RBI", "RUNS",
)


def _rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [x for x in value if isinstance(x, Mapping)]


def build_market_coverage(*, card_payload: Mapping[str, Any] | None, game_odds_payload: Mapping[str, Any] | None) -> dict[str, Any]:
    card_payload = card_payload or {}
    game_odds_payload = game_odds_payload or {}
    card_rows = _rows(card_payload.get("results"))
    game_quotes = _rows(game_odds_payload.get("quotes"))

    card_by_market: dict[str, list[Mapping[str, Any]]] = {}
    for row in card_rows:
        market = str(row.get("market") or "UNKNOWN")
        card_by_market.setdefault(market, []).append(row)
    game_counts = Counter(str(row.get("market") or "UNKNOWN") for row in game_quotes)

    aliases = {
        "MONEYLINE": "MONEYLINE",
        "RUN_LINE": "RUN_LINE",
        "TOTALS": "TOTALS",
    }
    coverage: list[dict[str, Any]] = []
    for family in REQUIRED_MARKET_FAMILIES:
        rows = card_by_market.get(family, [])
        if rows:
            statuses = Counter(str(x.get("bet_status") or "UNKNOWN") for x in rows)
            if statuses.get("OFFICIAL_BET", 0) > 0:
                state = "ACTIONABLE"
            elif statuses.get("BLOCKED", 0) == len(rows):
                state = "BLOCKED"
            else:
                state = "EVALUATED"
            coverage.append({"market_family": family, "state": state, "rows": len(rows), "bet_status_counts": dict(statuses)})
            continue
        game_market = aliases.get(family)
        if game_market and game_counts.get(game_market, 0):
            coverage.append({"market_family": family, "state": "ACQUIRED_NO_MODEL", "rows": int(game_counts[game_market]), "bet_status_counts": {}})
            continue
        coverage.append({"market_family": family, "state": "NOT_FOUND", "rows": 0, "bet_status_counts": {}})

    return {
        "required_market_families": list(REQUIRED_MARKET_FAMILIES),
        "coverage": coverage,
        "complete_accounting": len(coverage) == len(REQUIRED_MARKET_FAMILIES),
        "card_run_status": card_payload.get("run_status", "MISSING"),
        "card_source_failures": len(_rows(card_payload.get("source_failures"))),
        "game_odds_failures": len(_rows(game_odds_payload.get("failures"))),
    }
