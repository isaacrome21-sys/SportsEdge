"""Price the unquoted side only from a supplied opposite quote.

This does not fit a model and does not create Model_P authority. A complement
probability is copied from an explicit opposite probability, from a supplied
push/tie probability, from a supplied count distribution, or from ``1 - model_p``
on a push-free two-way market. Integer lines with no supplied push mass stay
unpriced.
"""
from __future__ import annotations

from typing import Any, Mapping


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _half_line(value: Any) -> bool:
    number = _number(value)
    if number is None:
        return False
    doubled = round(number * 2.0)
    return abs(number * 2.0 - doubled) < 1e-9 and int(doubled) % 2 == 1


def _count_pmf(raw: Mapping[str, Any]) -> tuple[float, ...] | None:
    payload = raw.get("count_pmf")
    if payload is None:
        payload = raw.get("outcome_pmf")
    if not isinstance(payload, (list, tuple)) or not payload:
        return None
    weights: list[float] = []
    for item in payload:
        number = _number(item)
        if number is None or number < 0.0:
            return None
        weights.append(number)
    total = sum(weights)
    if total <= 0.0 or abs(total - 1.0) > 1e-6:
        return None
    return tuple(weights)


def _complement_from_count_pmf(raw: Mapping[str, Any], model_p: float) -> float | None:
    weights = _count_pmf(raw)
    line = _number(raw.get("line"))
    if weights is None or line is None:
        return None
    over = sum(weight for index, weight in enumerate(weights) if index > line + 1e-9)
    under = sum(weight for index, weight in enumerate(weights) if index < line - 1e-9)
    side = str(raw.get("side") or raw.get("selection") or "").strip().upper()
    if side == "OVER":
        if abs(over - model_p) > 1e-6:
            return None
        return under
    if side == "UNDER":
        if abs(under - model_p) > 1e-6:
            return None
        return over
    return None


def complement_model_p(raw: Mapping[str, Any], *, market: str = "") -> float | None:
    """Return the other side's probability, or None if it would be invented."""
    explicit = _number(raw.get("complement_model_p"))
    if explicit is None:
        explicit = _number(raw.get("opposite_model_p"))
    if explicit is not None:
        return round(explicit, 10) if 0.0 <= explicit <= 1.0 else None
    model_p = _number(raw.get("model_p"))
    if model_p is None or not 0.0 <= model_p <= 1.0:
        return None
    push = _number(raw.get("push_p"))
    if push is None:
        push = _number(raw.get("tie_p"))
    if push is not None:
        if not 0.0 <= push <= 1.0:
            return None
        value = 1.0 - model_p - push
        return round(value, 10) if 0.0 <= value <= 1.0 else None
    from_counts = _complement_from_count_pmf(raw, model_p)
    if from_counts is not None:
        return round(from_counts, 10) if 0.0 <= from_counts <= 1.0 else None
    name = str(market or raw.get("market") or "").strip().upper()
    if name == "FIRST_HOME_RUN":
        return None
    if raw.get("line") is None or raw.get("line") == "":
        return round(1.0 - model_p, 10)
    if _half_line(raw.get("line")):
        return round(1.0 - model_p, 10)
    return None
