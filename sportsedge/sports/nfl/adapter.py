"""NFL adapter for the shared football SportAdapter."""

from __future__ import annotations

from typing import Any


class NFLAdapter:
    sport = "nfl"

    def __init__(self, history_ingestor: Any | None = None) -> None:
        self.history_ingestor = history_ingestor

    def load_schedule(self, seasons: list[int]) -> Any:
        if self.history_ingestor is None:
            raise NotImplementedError("NFL history ingestor is not configured")
        return self.history_ingestor.load(seasons)

    def load_lines_history(self, seasons: list[int]) -> Any:
        if self.history_ingestor is None:
            raise NotImplementedError("NFL history ingestor is not configured")
        return self.history_ingestor.load(seasons)

    def build_features(self, asof_ts: Any, games: Any) -> Any:
        raise NotImplementedError("NFL M2 features are implemented in roadmap task 13")

    def margin_sigma(self, context: Any) -> float:
        raise NotImplementedError

    def total_sigma(self, context: Any) -> float:
        raise NotImplementedError

    def key_numbers(self) -> dict[int, float]:
        raise NotImplementedError

    def hfa_prior(self, venue: Any, context: Any) -> float:
        raise NotImplementedError
