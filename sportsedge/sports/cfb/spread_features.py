"""Point-in-time, market-blind CFB spread features.

Research only. Features are frozen by config/cfb_spread_features_prereg_v1.json.
Nothing reaches the card until the prereg success criteria are met.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class SpreadFeatureVector:
    """All features are point-in-time and market-blind."""
    qb_starter_continuity: float
    qb_backup_flag: int
    qb_backup_career_epa: float
    returning_offense_pct: float
    returning_defense_pct: float
    talent_composite: float
    talent_diff: float
    transfer_net_rating: float
    hc_first_year: int
    oc_first_year: int
    dc_first_year: int
    rest_days: float
    travel_miles: float
    timezone_change: int
    off_bye: int


def build_features(game: Mapping) -> SpreadFeatureVector:
    """Stub. Real implementations will pull only pre-kickoff data."""
    raise NotImplementedError("Feature builders land in later attempts")


def residual_weight_and_ci(residuals: list[float], seasons: list[int]) -> tuple[float, tuple[float, float]]:
    """Season-clustered 95% CI for the weight on a feature residual.
    Placeholder for the exact #1954 harness once ChatGPT supplies it.
    """
    # TODO: replace with the reusable function from #1954
    return 0.0, (0.0, 0.0)
