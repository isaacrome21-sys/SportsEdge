"""JSON input contracts for one-command hitter-card execution."""
from __future__ import annotations

from typing import Any, Mapping

from .quote_bridge import QuoteBridgeError, validate_canonical_quote


class CardIOError(ValueError):
    pass


def normalize_feature_rows(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        raise CardIOError("feature file must contain a JSON list")
    out: list[dict[str, Any]] = []
    for i, row in enumerate(data):
        if not isinstance(row, Mapping):
            raise CardIOError(f"feature row {i} must be an object")
        out.append(dict(row))
    return out


def normalize_quotes(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        raise CardIOError("quote file must contain a JSON list")
    out: list[dict[str, Any]] = []
    for i, row in enumerate(data):
        if not isinstance(row, Mapping):
            raise CardIOError(f"quote row {i} must be an object")
        try:
            out.append(validate_canonical_quote(row))
        except QuoteBridgeError as exc:
            raise CardIOError(f"quote row {i}: {exc}") from exc
    return out
