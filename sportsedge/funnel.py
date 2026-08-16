"""Run-level MLB betting funnel instrumentation.

This module deliberately distinguishes infrastructure/data failures from a valid
no-edge slate. It only summarizes already-produced model/card rows; it does not
change Model_P, sportsbook prices, thresholds, or deployment decisions.
"""
from __future__ import annotations

from collections import Counter
from math import isfinite
from typing import Any, Iterable, Mapping


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _row_value(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def build_funnel(
    *,
    results: Iterable[Any],
    source_failures: Iterable[Mapping[str, Any]] = (),
    games_scheduled: int | None = None,
    lineups_confirmed: int | None = None,
    features_built: int | None = None,
) -> dict[str, Any]:
    rows = list(results)
    failures = list(source_failures)

    priced = [row for row in rows if _finite_number(_row_value(row, "model_p")) is not None]
    edge_rows: list[dict[str, Any]] = []
    for row in priced:
        edge = _finite_number(_row_value(row, "edge"))
        if edge is None:
            continue
        edge_rows.append({
            "game_id": str(_row_value(row, "game_id", "UNKNOWN")),
            "market": str(_row_value(row, "market", "UNKNOWN")),
            "entity_id": str(_row_value(row, "entity_id", "UNKNOWN")),
            "line": _row_value(row, "line"),
            "side": str(_row_value(row, "side", "UNKNOWN")),
            "american_odds": _row_value(row, "american_odds"),
            "model_p": _finite_number(_row_value(row, "model_p")),
            "implied_probability": _finite_number(_row_value(row, "implied_probability")),
            "edge": edge,
            "ev_per_dollar": _finite_number(_row_value(row, "ev_per_dollar")),
            "bet_status": str(_row_value(row, "bet_status", "UNKNOWN")),
            "shadow_status": _row_value(row, "shadow_status"),
            "reason": str(_row_value(row, "reason", "")),
        })
    edge_rows.sort(key=lambda x: x["edge"], reverse=True)

    reason_counts: Counter[str] = Counter()
    for row in rows:
        status = str(_row_value(row, "bet_status", ""))
        shadow = str(_row_value(row, "shadow_status", "") or "")
        if status not in {"OFFICIAL_BET"} and shadow not in {"SHADOW_BET"}:
            reason = str(_row_value(row, "reason", "UNKNOWN") or "UNKNOWN")
            reason_counts[reason] += 1
    for failure in failures:
        reason_counts[str(failure.get("reason") or "SOURCE_FAILURE")] += 1

    official_bets = sum(str(_row_value(row, "bet_status", "")) == "OFFICIAL_BET" for row in rows)
    shadow_bets = sum(str(_row_value(row, "shadow_status", "") or "") == "SHADOW_BET" for row in rows)
    blocked = sum(str(_row_value(row, "bet_status", "")) == "BLOCKED" for row in rows)

    # Quote/cardinality is preserved by the automated runner: every accepted or
    # rejected sportsbook row becomes a result row. A zero here means nothing
    # reached pricing and is an infrastructure/data failure, not "no edge".
    odds_rows_fetched = len(rows)
    model_priced = len(priced)
    positive_edge = sum(item["edge"] > 0 for item in edge_rows)

    health = "OK"
    health_reason = "VALID_PIPELINE"
    if odds_rows_fetched == 0:
        health = "BROKEN"
        health_reason = "NO_ODDS_ROWS"
    elif model_priced == 0:
        health = "BROKEN"
        health_reason = "NO_MODEL_PRICES"
    elif official_bets == 0 and shadow_bets == 0:
        health = "OK"
        health_reason = "VALID_NO_BET_SLATE"

    return {
        "games_scheduled": games_scheduled,
        "odds_rows_fetched": odds_rows_fetched,
        "lineups_confirmed": lineups_confirmed,
        "features_built": features_built,
        "model_priced": model_priced,
        "edge_positive": positive_edge,
        "shadow_bets": shadow_bets,
        "bets_emitted": official_bets,
        "blocked_rows": blocked,
        "pipeline_health": health,
        "pipeline_health_reason": health_reason,
        "gate_kill_counts": dict(reason_counts.most_common()),
        "edge_distribution": edge_rows,
    }


def pipeline_is_broken(funnel: Mapping[str, Any]) -> bool:
    return str(funnel.get("pipeline_health")) == "BROKEN"
