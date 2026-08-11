"""JSON input contracts for one-command hitter-card execution."""
from __future__ import annotations

from typing import Any, Mapping

from .runtime import parse_timestamp, RuntimeInputError


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
        q = dict(row)
        if "retrieved_at" not in q:
            raise CardIOError(f"quote row {i} missing retrieved_at")
        if isinstance(q["retrieved_at"], str):
            try:
                q["retrieved_at"] = parse_timestamp(q["retrieved_at"])
            except RuntimeInputError as exc:
                raise CardIOError(f"quote row {i} has invalid retrieved_at") from exc
        out.append(q)
    return out
