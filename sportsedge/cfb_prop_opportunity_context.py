"""Objective CFB prop-opportunity context for SportsEdge RUN IT.

Social graphics/posts are reminders only and never become feature data. Only
independently sourced, PIT-safe objective observations may populate this sidecar.
Everything starts outside Model_P and Truth Gate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

MODEL_P_ELIGIBLE = False
TRUTH_GATE_ELIGIBLE = False

PROP_FAMILIES = {
    "qb_passing": (
        "expected_snaps", "pass_attempt_share", "pace_total_plays", "game_script",
        "blowout_risk", "opponent_pass_defense", "weather", "coaching_tendency",
        "scheme_fit", "depth_chart_risk", "efficiency_profile",
    ),
    "wr_te_receiving": (
        "snap_share", "route_participation", "target_share", "adot", "yac_profile",
        "pace_total_plays", "game_script", "blowout_risk", "opponent_pass_defense",
        "weather", "depth_chart_risk", "efficiency_profile",
    ),
    "rb_rushing": (
        "snap_share", "carry_share", "early_down_role", "goal_line_packages",
        "pace_total_plays", "game_script", "blowout_risk", "opponent_run_defense",
        "weather", "coaching_tendency", "depth_chart_risk", "efficiency_profile",
    ),
    "rb_te_receiving": (
        "snap_share", "route_participation", "target_share", "third_down_role",
        "two_minute_role", "pace_total_plays", "game_script", "opponent_pass_defense",
        "weather", "depth_chart_risk", "efficiency_profile",
    ),
    "anytime_touchdown": (
        "snap_share", "goal_line_packages", "red_zone_usage", "red_zone_target_share",
        "goal_line_carry_share", "team_red_zone_rate", "game_script", "blowout_risk",
        "opponent_red_zone_defense", "depth_chart_risk",
    ),
    "qb_rushing": (
        "expected_snaps", "designed_run_share", "scramble_rate", "pressure_matchup",
        "man_coverage_rate", "red_zone_usage", "game_script", "blowout_risk",
        "weather", "depth_chart_risk", "efficiency_profile",
    ),
}

PROHIBITED_KEYS = {
    "social_pick", "handicapper_pick", "public_betting", "ticket_pct", "handle_pct",
    "sportsbook_price", "odds", "market_probability", "closing_line", "closing_price",
}

@dataclass(frozen=True)
class CFBPropOpportunityObservation:
    game_id: str
    entity_id: str
    prop_family: str
    as_of_utc: str
    source_uri: str
    source_sha256: str
    features: Mapping[str, Any] = field(default_factory=dict)
    sport: str = "CFB"
    subdivision: str = "FBS"
    lane: str = "HYBRID_CONTEXT"
    collection_mode: str = "AUTO"
    model_p_eligible: bool = MODEL_P_ELIGIBLE
    truth_gate_eligible: bool = TRUTH_GATE_ELIGIBLE

    def __post_init__(self) -> None:
        if self.subdivision != "FBS":
            raise ValueError("CFB prop context is FBS-only")
        if self.prop_family not in PROP_FAMILIES:
            raise ValueError(f"unsupported prop_family: {self.prop_family}")
        contaminated = PROHIBITED_KEYS.intersection(self.features)
        if contaminated:
            raise ValueError(f"market/social contamination prohibited: {sorted(contaminated)}")
        unknown = set(self.features) - set(PROP_FAMILIES[self.prop_family])
        if unknown:
            raise ValueError(f"unknown/unapproved features: {sorted(unknown)}")
        if self.model_p_eligible or self.truth_gate_eligible:
            raise ValueError("CFB prop context cannot be Model_P/Truth-Gate eligible at birth")


def prop_evaluation_sequence() -> tuple[str, ...]:
    return (
        "confirm_depth_chart_and_snap_expectations",
        "role_and_usage_share",
        "game_script_spread_and_blowout_risk",
        "matchup_defense_and_weather",
        "skill_and_efficiency_profile",
        "distribution",
        "market_price",
        "ev",
        "execution_gate",
    )
