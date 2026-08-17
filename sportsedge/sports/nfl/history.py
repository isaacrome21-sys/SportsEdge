"""NFL historical schedule/line ingestion primitives.

This module intentionally uses only the standard library. The repository's
current CI installs numpy only, and FOOTBALL_ROADMAP.md forbids adding new
dependencies without approval. A caller can inject a parquet writer when one
is available; normalization and acceptance accounting remain dependency-free.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

NFLVERSE_SCHEDULE_CSV = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"

_FLOAT_COLUMNS = {
    "away_moneyline",
    "home_moneyline",
    "spread_line",
    "away_spread_odds",
    "home_spread_odds",
    "total_line",
    "under_odds",
    "over_odds",
}
_INT_COLUMNS = {"season", "week", "away_score", "home_score"}


def _coerce(value: Any, kind: type) -> Any:
    if value is None or value == "":
        return None
    try:
        return kind(value)
    except (TypeError, ValueError):
        return None


def parse_schedule_csv(text: str) -> list[dict[str, Any]]:
    return [dict(row) for row in csv.DictReader(io.StringIO(text))]


def normalize_nfl_rows(rows: Iterable[Mapping[str, Any]], seasons: Iterable[int]) -> list[dict[str, Any]]:
    wanted = {int(season) for season in seasons}
    normalized: list[dict[str, Any]] = []
    for raw in rows:
        season = _coerce(raw.get("season"), int)
        if season not in wanted:
            continue
        row = dict(raw)
        for column in _FLOAT_COLUMNS:
            if column in row:
                row[column] = _coerce(row.get(column), float)
        for column in _INT_COLUMNS:
            if column in row:
                row[column] = _coerce(row.get(column), int)
        normalized.append(row)
    return normalized


def null_rates(rows: Iterable[Mapping[str, Any]], columns: Iterable[str]) -> dict[str, float]:
    materialized = list(rows)
    if not materialized:
        return {column: 1.0 for column in columns}
    total = float(len(materialized))
    return {
        column: sum(1 for row in materialized if row.get(column) in (None, "")) / total
        for column in columns
    }


def era_report(rows: Iterable[Mapping[str, Any]], columns: Iterable[str], eras: Iterable[tuple[int, int]]) -> list[dict[str, Any]]:
    materialized = list(rows)
    out: list[dict[str, Any]] = []
    for start, end in eras:
        chunk = [row for row in materialized if start <= int(row["season"]) <= end]
        out.append({"start_season": start, "end_season": end, "row_count": len(chunk), "null_rates": null_rates(chunk, columns)})
    return out


class NFLHistoryIngestor:
    """Bulk NFL history loader with injectable transport and parquet writer."""

    def __init__(
        self,
        fetch_text: Callable[[str], str],
        parquet_writer: Callable[[list[dict[str, Any]], Path], None] | None = None,
    ) -> None:
        self.fetch_text = fetch_text
        self.parquet_writer = parquet_writer

    def load(self, seasons: Iterable[int]) -> list[dict[str, Any]]:
        text = self.fetch_text(NFLVERSE_SCHEDULE_CSV)
        return normalize_nfl_rows(parse_schedule_csv(text), seasons)

    def ingest(self, seasons: Iterable[int], destination: str | Path) -> list[dict[str, Any]]:
        rows = self.load(seasons)
        if self.parquet_writer is None:
            raise RuntimeError("PARQUET_WRITER_NOT_CONFIGURED")
        path = Path(destination)
        if path.suffix != ".parquet":
            raise ValueError("NFL history cache destination must end in .parquet")
        self.parquet_writer(rows, path)
        return rows
