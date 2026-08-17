"""CFB historical games/lines bulk-ingestion primitives.

Network transport and parquet writing are injected so CI remains deterministic
and the core package adds no undeclared dependency.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any


class CFBHistoryIngestor:
    """Bulk by season, never per game, with a hard API-call budget."""

    def __init__(
        self,
        fetch_json: Callable[[str, int], list[dict[str, Any]]],
        max_calls: int = 100,
        parquet_writer: Callable[[list[dict[str, Any]], Path], None] | None = None,
    ) -> None:
        self.fetch_json = fetch_json
        self.max_calls = int(max_calls)
        self.parquet_writer = parquet_writer
        self.call_count = 0

    def _fetch(self, endpoint: str, season: int) -> list[dict[str, Any]]:
        if self.call_count >= self.max_calls:
            raise RuntimeError("CFBD_API_CALL_BUDGET_EXCEEDED")
        self.call_count += 1
        return list(self.fetch_json(endpoint, int(season)))

    def load(self, seasons: Iterable[int]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for season in seasons:
            season = int(season)
            for endpoint in ("games", "lines"):
                for item in self._fetch(endpoint, season):
                    row = dict(item)
                    row["source_endpoint"] = endpoint
                    row["season"] = int(row.get("season", season))
                    rows.append(row)
        return rows

    def ingest(self, seasons: Iterable[int], destination: str | Path) -> list[dict[str, Any]]:
        rows = self.load(seasons)
        if self.parquet_writer is None:
            raise RuntimeError("PARQUET_WRITER_NOT_CONFIGURED")
        path = Path(destination)
        if path.suffix != ".parquet":
            raise ValueError("CFB history cache destination must end in .parquet")
        self.parquet_writer(rows, path)
        return rows
