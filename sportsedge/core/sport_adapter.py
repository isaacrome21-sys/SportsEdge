"""Shared football sport adapter contract.

The core football stack consumes this interface so NFL and CFB share one
simulation, calibration, walk-forward, CLV, and gate implementation.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SportAdapter(Protocol):
    """Boundary between sport-specific data/features and shared core logic."""

    sport: str

    def load_schedule(self, seasons: list[int]) -> Any: ...

    def load_lines_history(self, seasons: list[int]) -> Any: ...

    def build_features(self, asof_ts: Any, games: Any) -> Any: ...

    def margin_sigma(self, context: Any) -> float: ...

    def total_sigma(self, context: Any) -> float: ...

    def key_number_validation_targets(self) -> dict[int, float]: ...

    # Legacy compatibility seam. Implementations must not use historical key
    # frequencies as simulator inputs; compliant adapters fail closed here.
    def key_numbers(self) -> dict[int, float]: ...

    def hfa_prior(self, venue: Any, context: Any) -> float: ...
