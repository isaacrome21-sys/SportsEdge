"""CFB total key-number execution context.

This module is intentionally NOT a predictive model feature. It stores an external
reference set of frequently occurring college-football final totals and exposes
helpers for execution/timing decisions around a market total.

Governance:
- model_p = False
- promotion_eligible = False
- source status is EXTERNAL_REFERENCE_ONLY until independently re-derived from a
  declared historical dataset and validation plan.
- key totals may affect price/timing/playable-to decisions, but never determine
  Over/Under direction or manufacture edge.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable

REFERENCE_ID = "CFB_TOTAL_KEYS_FUHRMAN_2026_09_05_V1"
REFERENCE_STATUS = "EXTERNAL_REFERENCE_ONLY"
MODEL_P = False
PROMOTION_ELIGIBLE = False

# User-provided Todd Fuhrman X post, timestamped 2026-09-05 09:07 AM.
# Preserve the published ordering/tiering; do not silently re-rank.
TIER_1_CRITICAL = (55, 48, 58, 44, 51)
TIER_2_HIGH = (41, 45, 65, 59, 52)
TIER_3_ELEVATED = (62, 69, 37, 47, 49)
TIER_4_MODERATE = (61, 38, 66, 54, 63, 57, 34, 56, 43, 40)

PUBLISHED_CUMULATIVE_SHARE = {
    "top_5": 0.15,
    "top_10": 0.27,
    "top_15": 0.36,
}

_TIER_MAP = {
    **{float(x): (1, "CRITICAL") for x in TIER_1_CRITICAL},
    **{float(x): (2, "HIGH") for x in TIER_2_HIGH},
    **{float(x): (3, "ELEVATED") for x in TIER_3_ELEVATED},
    **{float(x): (4, "MODERATE") for x in TIER_4_MODERATE},
}


@dataclass(frozen=True)
class KeyTotalContext:
    market_total: float
    nearest_key: float
    distance: float
    tier: int
    tier_name: str
    reference_id: str = REFERENCE_ID
    reference_status: str = REFERENCE_STATUS
    model_p: bool = MODEL_P
    promotion_eligible: bool = PROMOTION_ELIGIBLE


def _number(value: float, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}_NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise ValueError(f"{name}_FINITE_REQUIRED")
    return out


def all_key_totals() -> tuple[float, ...]:
    """Return the reference-set totals, sorted numerically."""
    return tuple(sorted(_TIER_MAP))


def key_total_context(market_total: float) -> KeyTotalContext:
    """Describe the nearest published key total to a market total.

    This function carries no Over/Under recommendation. It is an execution helper
    only, suitable for displaying whether a quoted total is sitting on/near a key.
    """
    total = _number(market_total, "market_total")
    nearest = min(_TIER_MAP, key=lambda key: (abs(total - key), _TIER_MAP[key][0], key))
    tier, name = _TIER_MAP[nearest]
    return KeyTotalContext(
        market_total=total,
        nearest_key=nearest,
        distance=abs(total - nearest),
        tier=tier,
        tier_name=name,
    )


def crossed_key_totals(start_total: float, end_total: float) -> tuple[KeyTotalContext, ...]:
    """Return published key totals crossed by a market move.

    A key is considered crossed when it lies strictly between start and end. This
    avoids double-counting a market that merely starts or ends exactly on a key.
    Returned items are ordered in the direction of the move.
    """
    start = _number(start_total, "start_total")
    end = _number(end_total, "end_total")
    if start == end:
        return ()
    low, high = sorted((start, end))
    keys = [key for key in _TIER_MAP if low < key < high]
    keys.sort(reverse=end < start)
    return tuple(key_total_context(key) for key in keys)


def execution_flags(current_total: float, previous_total: float | None = None) -> dict[str, object]:
    """Build a compact RUN IT execution payload for a CFB total quote."""
    current = key_total_context(current_total)
    crossed: Iterable[KeyTotalContext] = ()
    if previous_total is not None:
        crossed = crossed_key_totals(previous_total, current_total)
    return {
        "market_total": current.market_total,
        "nearest_key_total": current.nearest_key,
        "distance_to_key": current.distance,
        "key_tier": current.tier,
        "key_tier_name": current.tier_name,
        "crossed_keys": [
            {"key": item.nearest_key, "tier": item.tier, "tier_name": item.tier_name}
            for item in crossed
        ],
        "reference_id": REFERENCE_ID,
        "reference_status": REFERENCE_STATUS,
        "model_p": MODEL_P,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "direction_signal": None,
    }
