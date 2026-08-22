"""Market-specific MLB environment effects.

Environment is separated by outcome channel so a park/weather condition can move
HR, XBH, run scoring, and strikeout projections differently. Values are multiplicative
factors where 1.0 is neutral.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class EnvironmentEffects:
    hr: float = 1.0
    xbh: float = 1.0
    runs: float = 1.0
    strikeouts: float = 1.0

    def __post_init__(self) -> None:
        for name, value in (("hr", self.hr), ("xbh", self.xbh), ("runs", self.runs), ("strikeouts", self.strikeouts)):
            if not isfinite(value) or value <= 0:
                raise ValueError(f"{name} environment factor must be finite and > 0")


def from_percent_adjustments(*, hr_pct: float = 0.0, xbh_pct: float = 0.0, runs_pct: float = 0.0, k_pct: float = 0.0) -> EnvironmentEffects:
    """Convert percentage adjustments such as +20% xHR to multipliers."""
    return EnvironmentEffects(
        hr=1.0 + hr_pct / 100.0,
        xbh=1.0 + xbh_pct / 100.0,
        runs=1.0 + runs_pct / 100.0,
        strikeouts=1.0 + k_pct / 100.0,
    )
