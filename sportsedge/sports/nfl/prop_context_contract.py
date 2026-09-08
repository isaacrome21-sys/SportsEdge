"""Formal NFL prop-context contract layered on PIT opportunity features.

This contract defines which objective concepts RUN IT should request by prop
family and the mandatory evaluation ordering. It does not ingest markets or
social/public betting into NFL_HYBRID_CONTEXT and is not Model_P/Truth Gate data.

Market/research sidecars (including MySpariEdge historical prop trends) are
allowed for reporting and conflict awareness only.  They are explicitly barred
from this objective hybrid-context payload so they cannot become hidden model
features.
"""
from __future__ import annotations

MODEL_P_ELIGIBLE = False
TRUTH_GATE_ELIGIBLE = False

NFL_PROP_FAMILIES = {
    "QB_PASSING": ("attempts", "yards", "touchdowns", "completions"),
    "WR_TE_RECEIVING": ("routes", "targets", "receiving_yards", "longest_reception", "adot"),
    "RB_RUSHING": ("carry_share", "rushing_yards", "rushing_attempts"),
    "RB_RECEIVING": ("routes", "targets", "receptions", "receiving_yards"),
    "ANYTIME_TD": ("red_zone_role", "goal_line_carries", "red_zone_targets"),
    "QB_RUSHING": ("designed_runs", "scrambles", "rushing_yards"),
}

OBJECTIVE_CONCEPTS = (
    "usage_and_opportunity",
    "defined_role",
    "game_script",
    "pace",
    "weather",
    "injuries",
    "red_zone_role",
    "goal_line_role",
    "pass_run_mix",
    "adot",
    "target_share",
    "carry_share",
    "yac_ability",
    "red_zone_success_rate",
    "team_td_rate_inside_20",
)

RUN_IT_SEQUENCE = (
    "confirm_depth_chart_and_expected_snaps",
    "role_and_usage_share",
    "game_script_and_projected_score",
    "matchup_defense_weather_and_injuries",
    "skill_and_efficiency_profile",
    "distribution",
    "market_price",
    "ev",
    "execution_gate",
)

PROHIBITED_HYBRID_CONTEXT_FIELDS = frozenset({
    "social_pick", "handicapper_pick", "public_betting", "ticket_pct", "handle_pct",
    "sportsbook", "sportsbook_price", "odds", "market_probability", "closing_line",
    "closing_price", "consensus_line", "historical_hit_rate", "trend_hit_rate",
    "trend_windows", "myspariedge_trends",
})

PROHIBITED_HYBRID_CONTEXT_SOURCES = frozenset({
    "MYSPARIEDGE",
    "SPORTS_BETTING_SIMPLIFIED",
})

PROHIBITED_HYBRID_CONTEXT_LANES = frozenset({
    "NFL_PROP_TREND_RESEARCH",
})


def validate_context_payload(payload: dict) -> None:
    contaminated = PROHIBITED_HYBRID_CONTEXT_FIELDS.intersection(payload)
    if contaminated:
        raise ValueError(f"prohibited NFL hybrid-context fields: {sorted(contaminated)}")
    source = str(payload.get("source") or payload.get("source_name") or "").strip().upper()
    if source in PROHIBITED_HYBRID_CONTEXT_SOURCES:
        raise ValueError(f"research source cannot enter NFL hybrid context: {source}")
    lane = str(payload.get("context_lane") or payload.get("lane") or "").strip().upper()
    if lane in PROHIBITED_HYBRID_CONTEXT_LANES:
        raise ValueError(f"research lane cannot enter NFL hybrid context: {lane}")
    if payload.get("model_p_eligible") not in (None, False):
        raise ValueError("NFL prop context must start outside Model_P")
    if payload.get("truth_gate_eligible") not in (None, False):
        raise ValueError("NFL prop context must start outside Truth Gate")
