"""CFB adapter for the shared football SportAdapter."""

from __future__ import annotations

from typing import Any

from .m2 import build_cfb_m2_features


class CFBAdapter:
    sport = "cfb"

    def __init__(self, history_ingestor: Any | None = None) -> None:
        self.history_ingestor = history_ingestor

    def load_schedule(self, seasons: list[int]) -> Any:
        if self.history_ingestor is None:
            raise NotImplementedError("CFB history ingestor is not configured")
        return self.history_ingestor.load(seasons)

    def load_lines_history(self, seasons: list[int]) -> Any:
        if self.history_ingestor is None:
            raise NotImplementedError("CFB history ingestor is not configured")
        return self.history_ingestor.load(seasons)

    def build_features(self, asof_ts: Any, games: Any) -> Any:
        """Mechanical adapter seam into the already-implemented CFB M2 builder.

        `asof_ts` is authoritative and overwrites any caller-supplied feature timestamp
        so the M2 point-in-time guard evaluates the adapter invocation itself.
        """
        def one(game: Any) -> dict[str, float | str]:
            if not isinstance(game, dict):
                raise TypeError("CFB feature source must be a mapping")
            source = dict(game)
            source["feature_asof_ts"] = asof_ts
            return build_cfb_m2_features(source)

        if isinstance(games, dict):
            return one(games)
        if isinstance(games, (list, tuple)):
            return [one(game) for game in games]
        raise TypeError("CFB games must be a mapping or sequence of mappings")

    def margin_sigma(self, context: Any) -> float:
        raise NotImplementedError("CFB margin sigma requires validated historical-window methodology")

    def total_sigma(self, context: Any) -> float:
        raise NotImplementedError("CFB total sigma requires validated historical-window methodology")

    def key_numbers(self) -> dict[int, float]:
        raise NotImplementedError("CFB key-number treatment requires emergent-margin design validation")

    def hfa_prior(self, venue: Any, context: Any) -> float:
        raise NotImplementedError("CFB HFA requires an empirical venue/context contract")
