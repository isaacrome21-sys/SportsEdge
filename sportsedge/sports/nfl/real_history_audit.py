"""Real-source NFL history auditing for football validation.

This does not claim M2 predictive superiority. It proves that the historical
market/outcome spine comes from a hash-bound public source and measures the
empirical score-margin mass needed by the simulator validation lane.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def _valid_sha256(value: str) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _null_rate(rows: list[Mapping[str, Any]], key: str) -> float:
    if not rows:
        return 1.0
    return sum(1 for row in rows if row.get(key) in (None, "")) / len(rows)


def audit_nfl_history_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    source_url: str,
    source_sha256: str,
) -> dict[str, Any]:
    data = [dict(row) for row in rows if str(row.get("game_type", "REG")) == "REG"]
    if not _valid_sha256(source_sha256):
        raise ValueError("SOURCE_SHA256_INVALID")
    if not source_url.startswith("https://"):
        raise ValueError("REAL_HISTORY_SOURCE_URL_REQUIRED")

    seasons = sorted({int(row["season"]) for row in data if row.get("season") not in (None, "")})
    if len(seasons) < 2:
        raise ValueError("REAL_HISTORY_REQUIRES_MULTIPLE_SEASONS")
    if not data:
        raise ValueError("REAL_HISTORY_EMPTY")

    margins: list[int] = []
    for row in data:
        home = row.get("home_score")
        away = row.get("away_score")
        if home in (None, "") or away in (None, ""):
            continue
        margins.append(int(home) - int(away))
    if not margins:
        raise ValueError("REAL_HISTORY_SCORES_MISSING")

    denominator = len(margins)
    absolute = [abs(x) for x in margins]
    margin_pmf = {
        str(k): sum(1 for value in absolute if value == k) / denominator
        for k in (1, 2, 3, 4, 6, 7, 8, 10, 14)
    }

    per_season = []
    for season in seasons:
        chunk = [row for row in data if int(row["season"]) == season]
        per_season.append({
            "season": season,
            "row_count": len(chunk),
            "spread_line_null_rate": _null_rate(chunk, "spread_line"),
            "total_line_null_rate": _null_rate(chunk, "total_line"),
        })

    return {
        "provenance": "REAL_PUBLIC_HISTORY",
        "source_url": source_url,
        "source_sha256": source_sha256.lower(),
        "seasons": seasons,
        "row_count": len(data),
        "scored_row_count": denominator,
        "line_null_rates": {
            "spread_line": _null_rate(data, "spread_line"),
            "total_line": _null_rate(data, "total_line"),
        },
        "margin_pmf": margin_pmf,
        "per_season": per_season,
    }
