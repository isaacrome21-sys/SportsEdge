"""Market-blind positional matchup features for football models.

This module captures how much target share a defense allows to WR/TE/RB
relative to expectation, discounts stale defensive tendencies for coordinator
and personnel turnover, then crosses that signal with the offense's actual
usage profile. This keeps the feature football-native: a defense that bleeds
TE targets matters much more against an offense that actually routes targets
to tight ends.

The feature is intentionally market-blind and is shared by NFL and CFB M2.
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
    """Weight prior positional tendency for coaching/personnel continuity."""
    returners = _finite(returning_defensive_starter_share, "returning_defensive_starter_share")
    if not 0.0 <= returners <= 1.0:
        raise ValueError("POSITION_MATCHUP_RETURNERS_OUT_OF_RANGE")
    base = 1.0 if bool(same_defensive_playcaller) else float(changed_playcaller_weight)
    return max(0.0, min(1.0, base * (0.50 + 0.50 * returners)))


def _usage_map(source: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return offensive positional target share if supplied.

    Accepted names are intentionally explicit and market-blind. Values should
    normally be fractional shares summing to approximately 1 across WR/TE/RB.
    """
    for key in ("offense_positional_target_share", "off_positional_target_share"):
        value = source.get(key)
        if value is not None:
            if not isinstance(value, Mapping):
                raise ValueError("POSITION_MATCHUP_USAGE_NOT_MAPPING")
            return value
    return None


def _usage_features(weighted_oe: Mapping[str, float], usage: Mapping[str, Any]) -> dict[str, float]:
    shares: dict[str, float] = {}
    for pos in POSITIONS:
        if pos not in usage:
            raise ValueError(f"POSITION_MATCHUP_MISSING:usage:{pos}")
        share = _finite(usage[pos], f"usage:{pos}")
        if not 0.0 <= share <= 1.0:
            raise ValueError(f"POSITION_MATCHUP_USAGE_OUT_OF_RANGE:{pos}")
        shares[pos] = share

    # Do not renormalize silently. WR/TE/RB should explain nearly all targets,
    # but allow small bookkeeping leakage for throwaways / unusual positions.
    total = sum(shares.values())
    if not 0.85 <= total <= 1.05:
        raise ValueError("POSITION_MATCHUP_USAGE_SUM_OUT_OF_RANGE")

    return {
        "off_wr_target_share": shares["WR"],
        "off_te_target_share": shares["TE"],
        "off_rb_target_share": shares["RB"],
        "wr_usage_x_opp_target_oe": shares["WR"] * weighted_oe["WR"],
        "te_usage_x_opp_target_oe": shares["TE"] * weighted_oe["TE"],
        "rb_usage_x_opp_target_oe": shares["RB"] * weighted_oe["RB"],
        "positional_target_matchup_pressure": sum(shares[p] * weighted_oe[p] for p in POSITIONS),
    }


def build_positional_matchup_features(source: Mapping[str, Any]) -> dict[str, float]:
    """Build defensive target-OE and offense-usage interaction features.

    Defensive source shapes:
      1. positional_target_share_oe_allowed={"WR": ..., "TE": ..., "RB": ...}
      2. positional_target_share_allowed + positional_target_share_expected

    Optional continuity inputs:
      same_defensive_playcaller (default True)
      returning_defensive_starter_share (default 1.0)

    Optional offensive interaction input:
      offense_positional_target_share={"WR": 0.xx, "TE": 0.xx, "RB": 0.xx}

    If offensive usage is absent, the defense-only features still price and
    the interaction layer simply does not emit. Player-prop pricing should
    separately block later if Engine B participation/usage is unresolved.
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
    weighted = {pos: oe[pos] * weight for pos in POSITIONS}

    features = {
        "opp_wr_target_share_oe_allowed": oe["WR"],
        "opp_te_target_share_oe_allowed": oe["TE"],
        "opp_rb_target_share_oe_allowed": oe["RB"],
        "opp_wr_target_share_oe_weighted": weighted["WR"],
        "opp_te_target_share_oe_weighted": weighted["TE"],
        "opp_rb_target_share_oe_weighted": weighted["RB"],
        "defensive_playcaller_continuity_weight": weight,
        "defensive_playcaller_changed": 0.0 if bool(source.get("same_defensive_playcaller", True)) else 1.0,
    }

    usage = _usage_map(source)
    if usage is not None:
        features.update(_usage_features(weighted, usage))
    return features
