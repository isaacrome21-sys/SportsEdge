"""CFB implementation shell for the shared football SportAdapter."""

from __future__ import annotations

from typing import Any


class CFBAdapter:
    sport = "cfb"

    def load_schedule(self, seasons: list[int]) -> Any:
        raise NotImplementedError("CFB schedule loading is implemented in roadmap task 4")

    def load_lines_history(self, seasons: list[int]) -> Any:
        raise NotImplementedError("CFB lines history is implemented in roadmap task 4")

    def build_features(self, asof_ts: Any, games: Any) -> Any:
        raise NotImplementedError("CFB M2 features are implemented in roadmap task 12")

    def margin_sigma(self, context: Any) -> float:
        raise NotImplementedError

    def total_sigma(self, context: Any) -> float:
        raise NotImplementedError

    def key_numbers(self) -> dict[int, float]:
        raise NotImplementedError

    def hfa_prior(self, venue: Any, context: Any) -> float:
        raise NotImplementedError
