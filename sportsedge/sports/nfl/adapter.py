"""NFL implementation shell for the shared football SportAdapter."""

from __future__ import annotations

from typing import Any


class NFLAdapter:
    sport = "nfl"

    def load_schedule(self, seasons: list[int]) -> Any:
        raise NotImplementedError("NFL schedule loading is implemented in roadmap task 3")

    def load_lines_history(self, seasons: list[int]) -> Any:
        raise NotImplementedError("NFL lines history is implemented in roadmap task 3")

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
