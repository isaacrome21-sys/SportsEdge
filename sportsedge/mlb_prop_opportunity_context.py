"""Objective MLB prop-opportunity context inspired by prop-process concepts.

Governance: social graphics/posts are never data. Only independently sourced,
PIT-safe observations may populate this sidecar. This module does not alter
Model_P or Truth Gate eligibility.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

MODEL_P_ELIGIBLE = False
TRUTH_GATE_ELIGIBLE = False

PROP_FAMILIES = {
    "pitcher_strikeouts": ("platoon", "pitcher_k_rate", "swstr_rate", "whiff_by_pitch", "chase_rate", "first_pitch_strike_rate", "park_k_factor", "weather_air_density", "recent_expected_form"),
    "batter_hits": ("platoon", "hard_hit_rate", "barrel_rate", "babip_vs_expected", "lineup_slot", "park_hit_factor", "weather", "recent_expected_form"),
    "total_bases": ("platoon", "hard_hit_rate", "barrel_rate", "iso", "slg_vs_expected", "lineup_slot", "rbi_slot", "park_run_factor", "weather_carry", "recent_expected_form"),
    "home_runs": ("platoon", "hard_hit_rate", "barrel_rate", "hr_fb_rate", "launch_angle", "park_hr_factor", "weather_wind_carry", "lineup_protection", "recent_expected_form"),
    "stolen_bases": ("sprint_speed", "attempt_rate", "success_rate", "catcher_throwing", "pitcher_hold_delivery", "lead_first_move", "park_surface", "weather", "recent_expected_form"),
}

PROHIBITED_KEYS = {
    "social_pick", "handicapper_pick", "public_betting", "ticket_pct", "handle_pct",
    "sportsbook_price", "odds", "market_probability", "closing_line", "closing_price",
}

@dataclass(frozen=True)
class MLBPropOpportunityObservation:
    game_id: str
    entity_id: str
    prop_family: str
    as_of_utc: str
    source_uri: str
    source_sha256: str
    features: Mapping[str, Any] = field(default_factory=dict)
    lane: str = "HYBRID_CONTEXT"
    collection_mode: str = "AUTO"
    model_p_eligible: bool = MODEL_P_ELIGIBLE
    truth_gate_eligible: bool = TRUTH_GATE_ELIGIBLE

    def __post_init__(self) -> None:
        if self.prop_family not in PROP_FAMILIES:
            raise ValueError(f"unsupported prop_family: {self.prop_family}")
        contaminated = PROHIBITED_KEYS.intersection(self.features)
        if contaminated:
            raise ValueError(f"market/social contamination prohibited: {sorted(contaminated)}")
        allowed = set(PROP_FAMILIES[self.prop_family])
        unknown = set(self.features) - allowed
        if unknown:
            raise ValueError(f"unknown/unapproved features: {sorted(unknown)}")
        if self.model_p_eligible or self.truth_gate_eligible:
            raise ValueError("MLB prop context cannot be Model_P/Truth-Gate eligible at birth")


def prop_evaluation_sequence() -> tuple[str, ...]:
    """Required RUN IT ordering; price/EV remain downstream of objective context."""
    return (
        "confirm_lineup_and_starter",
        "platoon_and_matchup",
        "park_weather_environment",
        "quality_of_contact_or_pitch_skill",
        "distribution",
        "market_price",
        "ev",
        "execution_gate",
    )
