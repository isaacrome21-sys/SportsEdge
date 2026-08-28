from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable


@dataclass(frozen=True)
class PinLocation:
    hole: int
    green_depth_yards: float
    front_yards: float | None = None
    side_yards: float | None = None
    near_water: bool = False
    near_bunker: bool = False
    back_pin: bool = False
    front_pin: bool = False
    edge_pin: bool = False

    def __post_init__(self) -> None:
        if type(self.hole) is not int or not 1 <= self.hole <= 18:
            raise ValueError("PGA_PIN_HOLE_INVALID")
        if isinstance(self.green_depth_yards, bool) or not isinstance(self.green_depth_yards, (int, float)) or not isfinite(float(self.green_depth_yards)) or self.green_depth_yards <= 0:
            raise ValueError("PGA_PIN_GREEN_DEPTH_INVALID")
        for label, value in (("front_yards", self.front_yards), ("side_yards", self.side_yards)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)) or float(value) < 0):
                raise ValueError(f"PGA_PIN_{label.upper()}_INVALID")
        if self.front_yards is not None and self.front_yards > self.green_depth_yards:
            raise ValueError("PGA_PIN_FRONT_BEYOND_GREEN")
        if any(type(value) is not bool for value in (self.near_water, self.near_bunker, self.back_pin, self.front_pin, self.edge_pin)):
            raise ValueError("PGA_PIN_FLAGS_MUST_BE_BOOL")
        if self.back_pin and self.front_pin:
            raise ValueError("PGA_PIN_FRONT_BACK_CONFLICT")


@dataclass(frozen=True)
class PinDifficulty:
    hole: int
    difficulty_strokes: float
    label: str


def pin_difficulty(pin: PinLocation) -> PinDifficulty:
    """Small capped course-setup adjustment; never a substitute for player skill."""
    score = 0.0
    if pin.front_yards is not None:
        if pin.front_yards <= 6:
            score += 0.05
        elif pin.front_yards >= pin.green_depth_yards - 6:
            score += 0.04
    if pin.side_yards is not None and pin.side_yards <= 6:
        score += 0.05
    if pin.edge_pin:
        score += 0.04
    if pin.near_water:
        score += 0.05
    if pin.near_bunker:
        score += 0.025
    if pin.front_pin or pin.back_pin:
        score += 0.015
    score = max(-0.03, min(0.16, score))
    label = "VERY_TOUGH" if score >= 0.11 else "TOUGH" if score >= 0.07 else "ABOVE_AVERAGE" if score >= 0.035 else "NEUTRAL"
    return PinDifficulty(pin.hole, score, label)


def round_pin_adjustment(pins: Iterable[PinLocation]) -> float:
    values = list(pins)
    if not values:
        return 0.0
    holes = [pin.hole for pin in values]
    if len(set(holes)) != len(holes):
        raise ValueError("PGA_DUPLICATE_PIN_HOLE")
    # Cap the aggregate setup effect as an additional guard against noisy/manual inputs.
    return float(min(1.50, sum(pin_difficulty(pin).difficulty_strokes for pin in values)))
