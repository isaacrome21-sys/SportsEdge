"""Leakage-safe CFB v2 feature builder with explicit early-season prior decay.

The prior-decay artifact is learned outside this module on training seasons only. This
builder merely applies the frozen schedule. It blends prior/current opponent-adjusted
team efficiency before the predictive model sees the row; it never consults sportsbook
or market information.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

from sportsedge.core.leakage import assert_no_market_fields
from sportsedge.core.prior_decay import PriorDecayArtifact

from .joint_model_v2 import GAME_FEATURES_V2, TEAM_FEATURES_V2
from .prior_inputs import CFBPriorInputs


EFFICIENCY_METRICS = (
    "ppa_offense",
    "ppa_defense",
    "success_rate_offense",
    "success_rate_defense",
    "explosive_rate_offense",
    "explosive_rate_defense",
    "havoc_offense_allowed",
    "havoc_defense_created",
    "finishing_drives_offense",
    "finishing_drives_defense",
    "line_yards_offense",
    "line_yards_defense",
)


class CFBFeatureV2Error(ValueError):
    pass


def _num(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise CFBFeatureV2Error(f"{field}:NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBFeatureV2Error(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise CFBFeatureV2Error(f"{field}:FINITE_REQUIRED")
    return out


@dataclass(frozen=True)
class CFBAdjustedTeamState:
    team_id: str
    current_adjusted: Mapping[str, float]
    prior_adjusted: Mapping[str, float]
    current_pace: float
    prior_pace: float
    prior_inputs: CFBPriorInputs

    def validate(self) -> "CFBAdjustedTeamState":
        if not self.team_id:
            raise CFBFeatureV2Error("TEAM_ID_REQUIRED")
        assert_no_market_fields(self.current_adjusted)
        assert_no_market_fields(self.prior_adjusted)
        for metric in EFFICIENCY_METRICS:
            _num(self.current_adjusted.get(metric), f"current.{metric}")
            _num(self.prior_adjusted.get(metric), f"prior.{metric}")
        _num(self.current_pace, "current_pace")
        _num(self.prior_pace, "prior_pace")
        self.prior_inputs.validate()
        if self.prior_inputs.team_id != self.team_id:
            raise CFBFeatureV2Error("PRIOR_INPUT_TEAM_MISMATCH")
        return self


@dataclass(frozen=True)
class CFBGameContextV2:
    game_id: str
    season: int
    week: int
    game_start_ts: str
    feature_asof_ts: str
    neutral_site: bool
    hfa_points: float
    rest_diff_days: float
    travel_diff_miles: float
    timezone_crossing_diff: float
    altitude_diff_feet: float
    wind_speed: float
    temperature: float
    indoors: bool

    def to_model_features(self) -> dict[str, float]:
        if type(self.neutral_site) is not bool or type(self.indoors) is not bool:
            raise CFBFeatureV2Error("GAME_CONTEXT_BOOL_REQUIRED")
        hfa = _num(self.hfa_points, "hfa_points")
        if self.neutral_site and abs(hfa) > 1e-12:
            raise CFBFeatureV2Error("NEUTRAL_SITE_HFA_MUST_BE_ZERO")
        return {
            "hfa_points": hfa,
            "rest_diff_days": _num(self.rest_diff_days, "rest_diff_days"),
            "travel_diff_miles": _num(self.travel_diff_miles, "travel_diff_miles"),
            "timezone_crossing_diff": _num(self.timezone_crossing_diff, "timezone_crossing_diff"),
            "altitude_diff_feet": _num(self.altitude_diff_feet, "altitude_diff_feet"),
            "wind_speed": 0.0 if self.indoors else _num(self.wind_speed, "wind_speed"),
            "temperature": 70.0 if self.indoors else _num(self.temperature, "temperature"),
            "indoors": 1.0 if self.indoors else 0.0,
        }


def prior_weight_for_week(artifact: PriorDecayArtifact, week: int) -> float:
    schedule = artifact.as_schedule()
    target = int(week)
    if target <= 0:
        raise CFBFeatureV2Error("WEEK_INVALID")
    if target in schedule:
        return float(schedule[target])
    # The explicit early-season prior has fully decayed after the last scheduled week.
    if target > max(schedule):
        return 0.0
    raise CFBFeatureV2Error(f"PRIOR_DECAY_WEEK_UNDEFINED:{target}")


def build_team_features_v2(
    state: CFBAdjustedTeamState,
    *,
    prior_decay: PriorDecayArtifact,
    week: int,
) -> dict[str, float]:
    state.validate()
    weight = prior_weight_for_week(prior_decay, week)
    features: dict[str, float] = {}
    for metric in EFFICIENCY_METRICS:
        current = _num(state.current_adjusted[metric], f"current.{metric}")
        prior = _num(state.prior_adjusted[metric], f"prior.{metric}")
        features[f"adj_{metric}"] = weight * prior + (1.0 - weight) * current
    prior = state.prior_inputs.to_features()
    features.update({
        "prior_season_rating": float(prior["prior_season_rating"]) * weight,
        "returning_production": float(prior["returning_production"]),
        "talent_composite": float(prior["talent_composite"]) * weight,
        "portal_impact": float(prior["portal_impact"]) * weight,
        "qb_continuity": float(prior["qb_continuity"]),
        "ol_continuity": float(prior["ol_continuity"]),
        "skill_continuity": float(prior["skill_continuity"]),
        "defensive_continuity": float(prior["defensive_continuity"]),
        "coaching_continuity": float(prior["coaching_continuity"]),
        "special_teams_prior": float(prior["special_teams_prior"]) * weight,
        "pace": weight * _num(state.prior_pace, "prior_pace") + (1.0 - weight) * _num(state.current_pace, "current_pace"),
    })
    missing = sorted(set(TEAM_FEATURES_V2) - set(features))
    extra = sorted(set(features) - set(TEAM_FEATURES_V2))
    if missing or extra:
        raise CFBFeatureV2Error(f"TEAM_FEATURE_CONTRACT_MISMATCH:missing={missing}:extra={extra}")
    return features


def build_cfb_game_feature_row_v2(
    *,
    home: CFBAdjustedTeamState,
    away: CFBAdjustedTeamState,
    context: CFBGameContextV2,
    prior_decay: PriorDecayArtifact,
    realized_scores: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if home.team_id == away.team_id:
        raise CFBFeatureV2Error("SELF_MATCHUP_FORBIDDEN")
    if int(home.prior_inputs.season) != int(context.season) or int(away.prior_inputs.season) != int(context.season):
        raise CFBFeatureV2Error("PRIOR_INPUT_SEASON_MISMATCH")
    row: dict[str, Any] = {
        "game_id": context.game_id,
        "season": int(context.season),
        "week": int(context.week),
        "game_start_ts": context.game_start_ts,
        "feature_asof_ts": context.feature_asof_ts,
        "home_team_id": home.team_id,
        "away_team_id": away.team_id,
        "home_features": build_team_features_v2(home, prior_decay=prior_decay, week=context.week),
        "away_features": build_team_features_v2(away, prior_decay=prior_decay, week=context.week),
        "game_features": context.to_model_features(),
        "prior_version": prior_decay.prior_version,
        "prior_decay_hash": prior_decay.content_hash(),
    }
    if realized_scores is not None:
        # Realized outcomes may be appended only for historical fitting/evaluation. They
        # are explicitly excluded from the predictive feature vector.
        for field in ("home_score", "away_score", "regulation_home_score", "regulation_away_score"):
            if field in realized_scores:
                row[field] = _num(realized_scores[field], field)
    assert_no_market_fields({
        key: value for key, value in row.items()
        if key not in {"home_score", "away_score", "regulation_home_score", "regulation_away_score"}
    })
    return row
