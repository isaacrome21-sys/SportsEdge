"""Validate historical model rows before cross-sport scoring.

Do not infer timestamps or manufacture missing historical odds/model probabilities.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def validate_historical_row(row: dict[str, Any]) -> tuple[str, ...]:
    errors: list[str] = []
    for field in ("sport", "market", "event_id", "season", "event_start_ts",
                  "decision_ts", "feature_asof_ts", "model_p"):
        if row.get(field) is None or row.get(field) == "":
            errors.append("MISSING_" + field.upper())
    times: dict[str, datetime] = {}
    for field in ("event_start_ts", "decision_ts", "feature_asof_ts", "odds_captured_at"):
        value = row.get(field)
        if value is None and field == "odds_captured_at":
            continue
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("naive")
            times[field] = parsed
        except ValueError:
            errors.append("INVALID_" + field.upper())
    if all(k in times for k in ("feature_asof_ts", "decision_ts", "event_start_ts")):
        if times["feature_asof_ts"] > times["decision_ts"]:
            errors.append("FEATURE_AFTER_DECISION")
        if times["decision_ts"] >= times["event_start_ts"]:
            errors.append("DECISION_NOT_PRESTART")
    if "odds_captured_at" in times and "decision_ts" in times:
        if times["odds_captured_at"] > times["decision_ts"]:
            errors.append("ODDS_AFTER_DECISION")
    if row.get("offered_decimal") is not None:
        for field in ("bookmaker", "odds_captured_at"):
            if not row.get(field):
                errors.append("OFFERED_ODDS_MISSING_" + field.upper())
    if row.get("benchmark_p") is not None and not row.get("benchmark_source"):
        errors.append("BENCHMARK_SOURCE_MISSING")
    return tuple(dict.fromkeys(errors))
