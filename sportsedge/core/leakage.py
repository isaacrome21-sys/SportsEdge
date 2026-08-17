"""Fail-closed temporal leakage checks shared by football feature builders."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        raise ValueError("INVALID_TIMESTAMP")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_feature_asof_before_game(rows: Iterable[Mapping[str, Any]]) -> None:
    """Reject any row whose features are not strictly prior to kickoff."""

    for index, row in enumerate(rows):
        feature_ts = _parse_ts(row.get("feature_asof_ts"))
        game_ts = _parse_ts(row.get("game_start_ts"))
        if feature_ts >= game_ts:
            game_id = row.get("game_id", f"row_{index}")
            raise ValueError(f"FEATURE_TIME_LEAK:{game_id}")
