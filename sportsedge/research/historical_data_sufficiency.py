"""Historical evidence sufficiency grading for SportsEdge research.

A market is not backtest-ready merely because final scores/outcomes exist. This
module distinguishes probability-validation readiness from betting/CLV readiness
and fails closed when point-in-time features or exact historical quotes are absent.
It never grants production eligibility.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime
from math import isfinite
from typing import Any, Iterable, Mapping


class HistoricalDataSufficiencyError(ValueError):
    pass


def _present(value: Any) -> bool:
    return value is not None and value != ""


def _dt(value: Any, field: str) -> datetime:
    if not _present(value):
        raise HistoricalDataSufficiencyError(f"{field}:MISSING")
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise HistoricalDataSufficiencyError(f"{field}:INVALID_TIMESTAMP") from exc
    if dt.tzinfo is None:
        raise HistoricalDataSufficiencyError(f"{field}:NAIVE_TIMESTAMP")
    return dt


def _valid_prob(value: Any) -> bool:
    if not _present(value) or isinstance(value, bool):
        return False
    try:
        x = float(value)
    except (TypeError, ValueError):
        return False
    return isfinite(x) and 0.0 < x < 1.0


def _valid_decimal(value: Any) -> bool:
    if not _present(value) or isinstance(value, bool):
        return False
    try:
        x = float(value)
    except (TypeError, ValueError):
        return False
    return isfinite(x) and x > 1.0


def _valid_outcome(value: Any) -> bool:
    return value is None or value in (0, 1, True, False)


@dataclass(frozen=True)
class MarketDataSufficiency:
    sport: str
    market: str
    n_rows: int
    seasons: tuple[int, ...]
    pit_feature_rows: int
    model_probability_rows: int
    outcome_rows: int
    decision_quote_rows: int
    benchmark_probability_rows: int
    close_quote_rows: int
    clv_rows: int
    probability_validation_status: str
    betting_backtest_status: str
    clv_backtest_status: str
    blockers: tuple[str, ...]
    production_eligibility_changed: bool = False


def _identity(row: Mapping[str, Any]) -> tuple[str, str]:
    sport = str(row.get("sport") or "").strip().upper()
    market = str(row.get("market") or "").strip().upper()
    if not sport or not market:
        raise HistoricalDataSufficiencyError("SPORT_AND_MARKET_REQUIRED")
    return sport, market


def _pit_ok(row: Mapping[str, Any]) -> bool:
    try:
        feature = _dt(row.get("feature_asof_ts"), "feature_asof_ts")
        decision = _dt(row.get("decision_ts"), "decision_ts")
        event = _dt(row.get("event_start_ts"), "event_start_ts")
    except HistoricalDataSufficiencyError:
        return False
    return feature <= decision < event


def _season(row: Mapping[str, Any]) -> int | None:
    try:
        return int(row.get("season"))
    except (TypeError, ValueError):
        return None


def _has_outcome(row: Mapping[str, Any]) -> bool:
    return "outcome" in row and _valid_outcome(row.get("outcome"))


def _has_decision_quote(row: Mapping[str, Any]) -> bool:
    return _valid_decimal(row.get("offered_decimal")) and _present(row.get("decision_ts"))


def _has_close_quote(row: Mapping[str, Any]) -> bool:
    close_decimal = row.get("close_decimal", row.get("closing_decimal"))
    close_ts = row.get("close_ts", row.get("closing_ts"))
    return _valid_decimal(close_decimal) and _present(close_ts)


def _has_clv(row: Mapping[str, Any]) -> bool:
    value = row.get("clv_pct")
    if not _present(value) or isinstance(value, bool):
        return False
    try:
        return isfinite(float(value))
    except (TypeError, ValueError):
        return False


def grade_market_rows(
    rows: Iterable[Mapping[str, Any]], *,
    min_probability_rows: int = 200,
    min_betting_rows: int = 200,
    min_seasons: int = 3,
) -> MarketDataSufficiency:
    data = [dict(row) for row in rows]
    if not data:
        raise HistoricalDataSufficiencyError("EMPTY_MARKET_ROWS")
    identities = {_identity(row) for row in data}
    if len(identities) != 1:
        raise HistoricalDataSufficiencyError("MIXED_SPORT_OR_MARKET")
    sport, market = next(iter(identities))
    seasons = tuple(sorted({s for row in data if (s := _season(row)) is not None}))

    pit_rows = sum(_pit_ok(row) for row in data)
    model_rows = sum(_valid_prob(row.get("model_p")) for row in data)
    outcome_rows = sum(_has_outcome(row) for row in data)
    decision_rows = sum(_has_decision_quote(row) for row in data)
    benchmark_rows = sum(_valid_prob(row.get("benchmark_p")) for row in data)
    close_rows = sum(_has_close_quote(row) for row in data)
    clv_rows = sum(_has_clv(row) for row in data)

    blockers: list[str] = []
    if len(seasons) < min_seasons:
        blockers.append("INSUFFICIENT_SEASONS")
    probability_ready = (
        len(seasons) >= min_seasons
        and pit_rows >= min_probability_rows
        and model_rows >= min_probability_rows
        and outcome_rows >= min_probability_rows
    )
    if pit_rows < min_probability_rows:
        blockers.append("PIT_FEATURE_EVIDENCE_MISSING_OR_INSUFFICIENT")
    if model_rows < min_probability_rows:
        blockers.append("MODEL_PROBABILITY_HISTORY_MISSING_OR_INSUFFICIENT")
    if outcome_rows < min_probability_rows:
        blockers.append("SETTLED_OUTCOME_HISTORY_MISSING_OR_INSUFFICIENT")

    betting_ready = probability_ready and decision_rows >= min_betting_rows
    if decision_rows < min_betting_rows:
        blockers.append("DECISION_TIME_QUOTES_MISSING_OR_INSUFFICIENT")

    clv_ready = betting_ready and (clv_rows >= min_betting_rows or close_rows >= min_betting_rows)
    if clv_rows < min_betting_rows and close_rows < min_betting_rows:
        blockers.append("CLOSE_QUOTES_OR_CANONICAL_CLV_MISSING_OR_INSUFFICIENT")

    return MarketDataSufficiency(
        sport=sport,
        market=market,
        n_rows=len(data),
        seasons=seasons,
        pit_feature_rows=pit_rows,
        model_probability_rows=model_rows,
        outcome_rows=outcome_rows,
        decision_quote_rows=decision_rows,
        benchmark_probability_rows=benchmark_rows,
        close_quote_rows=close_rows,
        clv_rows=clv_rows,
        probability_validation_status="READY" if probability_ready else "NOT_READY",
        betting_backtest_status="READY" if betting_ready else "NOT_READY",
        clv_backtest_status="READY" if clv_ready else "NOT_READY",
        blockers=tuple(dict.fromkeys(blockers)),
    )


def grade_all_markets(
    rows: Iterable[Mapping[str, Any]], *,
    min_probability_rows: int = 200,
    min_betting_rows: int = 200,
    min_seasons: int = 3,
) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for raw in rows:
        row = dict(raw)
        grouped.setdefault(_identity(row), []).append(row)
    if not grouped:
        raise HistoricalDataSufficiencyError("EMPTY_HISTORY")
    reports = [
        grade_market_rows(
            market_rows,
            min_probability_rows=min_probability_rows,
            min_betting_rows=min_betting_rows,
            min_seasons=min_seasons,
        )
        for _, market_rows in sorted(grouped.items())
    ]
    counts = Counter(report.clv_backtest_status for report in reports)
    return {
        "schema_version": 1,
        "report_type": "SPORTSEDGE_HISTORICAL_DATA_SUFFICIENCY",
        "production_eligibility_changed": False,
        "market_count": len(reports),
        "clv_ready_market_count": int(counts.get("READY", 0)),
        "markets": [asdict(report) for report in reports],
    }
