from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class PinLocation:
    """Normalized daily hole-location input.

    Distances are yards from the front and from the nearest lateral green edge.
    If the source only supports a qualitative read, leave a distance as None and
    provide the risk flags instead. This prevents inventing precision from an image.
    """

    hole: int
    green_depth_yards: float
    front_yards: float | None = None
    side_yards: float | None = None
    near_water: bool = False
    near_bunker: bool = False
    back_pin: bool = False
    front_pin: bool = False
    edge_pin: bool = False


@dataclass(frozen=True)
class PinDifficulty:
    hole: int
    difficulty_strokes: float
    label: str


def pin_difficulty(pin: PinLocation) -> PinDifficulty:
    """Return a small hole-level scoring adjustment from daily pin placement.

    This is intentionally conservative. Pin placement should refine course setup,
    not overwhelm player skill. Positive values mean a tougher-than-neutral pin.
    """

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

    # Cap one pin from dominating a round projection.
    score = max(-0.03, min(0.16, score))
    if score >= 0.11:
        label = "VERY_TOUGH"
    elif score >= 0.07:
        label = "TOUGH"
    elif score >= 0.035:
        label = "ABOVE_AVERAGE"
    else:
        label = "NEUTRAL"
    return PinDifficulty(pin.hole, score, label)


def round_pin_adjustment(pins: Iterable[PinLocation]) -> float:
    """Aggregate daily hole locations into an expected strokes adjustment."""

    values = [pin_difficulty(pin).difficulty_strokes for pin in pins]
    return float(sum(values))
