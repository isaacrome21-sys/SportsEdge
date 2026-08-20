"""Market-blind positional matchup features for football models.

This module captures how much target share a defense allows to WR/TE/RB
relative to expectation. Positive values mean the defense allowed more target
share than expected to that position; negative values mean less.

The feature is intentionally market-blind and can be used by both NFL and CFB
M2 feature builders. A continuity weight discounts prior-season signal when
the defensive playcaller/scheme changed.
"""
from __future__ import annotations

from typing import Any, Mapping

POSITIONS = ("WR", "TE", "RB")


def _finite(value: Any, name: str) -> float:
    x = float(value)
    if x != x or x in (float("inf"), float("-inf")):
        raise ValueError(f"POSITION_MATCHUP_NONFINITE:{name}")
    return x


def positional_target_share_oe_allowed(
    actual_target_share: Mapping[str, Any],
    expected_target_share: Mapping[str, Any],
) -> dict[str, float]:
    """Return defense target-share over expected allowed by position.

    Inputs may be fractions (0.28) or percentage points (28.0), but both maps
    must use the same unit. The output preserves that unit.
    """
    out: dict[str, float] = {}
    for pos in POSITIONS:
        if pos not in actual_target_share:
            raise ValueError(f"POSITION_MATCHUP_MISSING:actual:{pos}")
        if pos not in expected_target_share:
            raise ValueError(f"POSITION_MATCHUP_MISSING:expected:{pos}")
        actual = _finite(actual_target_share[pos], f"actual:{pos}")
        expected = _finite(expected_target_share[pos], f"expected:{pos}")
        out[pos] = actual - expected
    return out


def continuity_weight(
    same_defensive_playcaller: Any,
    returning_defensive_starter_share: Any = 1.0,
    *,
    changed_playcaller_weight: float = 0.45,
) -> float:
    """Weight prior positional tendency for coaching/personnel continuity.

    Same playcaller retains more prior-year signal. A new playcaller sharply
    discounts it, while returning defensive starter share scales either case.
    """
    returners = _finite(returning_defensive_starter_share, "returning_defensive_starter_share")
    if not 0.0 <= returners <= 1.0:
        raise ValueError("POSITION_MATCHUP_RETURNERS_OUT_OF_RANGE")
    base = 1.0 if bool(same_defensive_playcaller) else float(changed_playcaller_weight)
    return max(0.0, min(1.0, base * (0.50 + 0.50 * returners)))


def build_positional_matchup_features(source: Mapping[str, Any]) -> dict[str, float]:
    """Build WR/TE/RB defensive target-OE features from a source mapping.

    Supported source shapes:
      1. positional_target_share_oe_allowed={"WR": ..., "TE": ..., "RB": ...}
      2. positional_target_share_allowed + positional_target_share_expected

    Optional continuity inputs:
      same_defensive_playcaller (default True)
      returning_defensive_starter_share (default 1.0)
    """
    if "positional_target_share_oe_allowed" in source:
        raw = source["positional_target_share_oe_allowed"]
        if not isinstance(raw, Mapping):
            raise ValueError("POSITION_MATCHUP_OE_NOT_MAPPING")
        oe = {}
        for pos in POSITIONS:
            if pos not in raw:
                raise ValueError(f"POSITION_MATCHUP_MISSING:oe:{pos}")
            oe[pos] = _finite(raw[pos], f"oe:{pos}")
    elif "positional_target_share_allowed" in source and "positional_target_share_expected" in source:
        actual = source["positional_target_share_allowed"]
        expected = source["positional_target_share_expected"]
        if not isinstance(actual, Mapping) or not isinstance(expected, Mapping):
            raise ValueError("POSITION_MATCHUP_SHARE_NOT_MAPPING")
        oe = positional_target_share_oe_allowed(actual, expected)
    else:
        return {}

    weight = continuity_weight(
        source.get("same_defensive_playcaller", True),
        source.get("returning_defensive_starter_share", 1.0),
    )

    return {
        "opp_wr_target_share_oe_allowed": oe["WR"],
        "opp_te_target_share_oe_allowed": oe["TE"],
        "opp_rb_target_share_oe_allowed": oe["RB"],
        "opp_wr_target_share_oe_weighted": oe["WR"] * weight,
        "opp_te_target_share_oe_weighted": oe["TE"] * weight,
        "opp_rb_target_share_oe_weighted": oe["RB"] * weight,
        "defensive_playcaller_continuity_weight": weight,
        "defensive_playcaller_changed": 0.0 if bool(source.get("same_defensive_playcaller", True)) else 1.0,
    }
