"""Unpromoted, price-independent first-inning matchup challenger.

Coefficient values must come from a separately frozen training artifact. There
are intentionally no purportedly fitted defaults and no production registration.
Half innings are conditionally independent *within* a supplied environment
scenario; callers may mix scenarios to retain shared-environment dependence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from math import exp, isfinite, log
from typing import Sequence

from sportsedge.source_lineage import canonical_json_sha256


def finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isfinite(float(value)):
        raise ValueError(f"INVALID:{name}")
    return float(value)


def aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("AWARE_TIMESTAMP_REQUIRED")
    return value


def shrink_rate(successes: int, trials: int, prior: float, strength: float) -> float:
    """Posterior mean; zero observations preserve the explicit prior."""
    if any(type(v) is not int for v in (successes, trials)) or not 0 <= successes <= trials:
        raise ValueError("INVALID_BINOMIAL_COUNTS")
    if not 0 < finite(prior, "prior") < 1 or finite(strength, "strength") <= 0:
        raise ValueError("INVALID_PRIOR")
    return (successes + strength * prior) / (trials + strength)


@dataclass(frozen=True)
class BatterOBP:
    player_id: str
    on_base: int
    obp_denominator: int  # AB + BB + HBP + SF, not an indiscriminate PA count

    def __post_init__(self):
        if not self.player_id:
            raise ValueError("BATTER_ID_REQUIRED")
        shrink_rate(self.on_base, self.obp_denominator, 0.5, 1.0)


@dataclass(frozen=True)
class PitcherFirstInning:
    pitcher_id: str
    strikeouts: int
    outs_recorded: int
    scoreless_starts: int
    starts: int

    def __post_init__(self):
        if not self.pitcher_id:
            raise ValueError("PITCHER_ID_REQUIRED")
        if type(self.strikeouts) is not int or self.strikeouts < 0:
            raise ValueError("INVALID_STRIKEOUTS")
        if type(self.outs_recorded) is not int or self.outs_recorded <= 0:
            raise ValueError("PITCHER_OUTS_REQUIRED")
        shrink_rate(self.scoreless_starts, self.starts, 0.5, 1.0)


@dataclass(frozen=True)
class FirstInningParameters:
    artifact_id: str
    training_end: datetime
    k9_intercept: float
    k9_slope: float
    top3_obp_coefficient: float
    log_run_factor_coefficient: float
    pitcher_prior_starts: float
    batter_prior_obp_denominator: float
    league_obp: float
    history_weight_cap: float

    def __post_init__(self):
        if not self.artifact_id:
            raise ValueError("TRAINING_ARTIFACT_ID_REQUIRED")
        aware(self.training_end)
        for name in ("k9_intercept", "k9_slope", "top3_obp_coefficient", "log_run_factor_coefficient"):
            finite(getattr(self, name), name)
        for name in ("pitcher_prior_starts", "batter_prior_obp_denominator"):
            if finite(getattr(self, name), name) <= 0:
                raise ValueError("POSITIVE_PRIOR_STRENGTH_REQUIRED")
        if not 0 < finite(self.league_obp, "league_obp") < 1:
            raise ValueError("INVALID_LEAGUE_OBP")
        if not 0 <= finite(self.history_weight_cap, "history_weight_cap") <= 0.5:
            raise ValueError("HISTORY_CANNOT_OUTWEIGH_BASELINE")


def _sigmoid(x: float) -> float:
    return 1 / (1 + exp(-x)) if x >= 0 else exp(x) / (1 + exp(x))


def _half(pitcher, lineup, parameters, run_factor):
    k9 = 27 * pitcher.strikeouts / pitcher.outs_recorded
    baseline = _sigmoid(parameters.k9_intercept + parameters.k9_slope * k9)
    # Numerical clipping is not a probability haircut or calibration claim.
    baseline = min(1 - 1e-12, max(1e-12, baseline))
    weight = min(parameters.history_weight_cap,
                 pitcher.starts / (pitcher.starts + parameters.pitcher_prior_starts))
    history = pitcher.scoreless_starts / pitcher.starts if pitcher.starts else baseline
    hold = baseline * (1 - weight) + history * weight
    obp = sum(shrink_rate(b.on_base, b.obp_denominator, parameters.league_obp,
                         parameters.batter_prior_obp_denominator) for b in lineup) / 3
    adjusted = _sigmoid(log(hold / (1 - hold))
                        + parameters.top3_obp_coefficient * (obp - parameters.league_obp)
                        + parameters.log_run_factor_coefficient * log(run_factor))
    return {"hold_probability": adjusted, "k9": k9, "history_weight": weight,
            "stabilized_top3_obp": obp, "baseline_hold_probability": baseline}


def predict_first_inning(*, away_pitcher: PitcherFirstInning,
                         home_pitcher: PitcherFirstInning,
                         away_top3: Sequence[BatterOBP], home_top3: Sequence[BatterOBP],
                         parameters: FirstInningParameters,
                         environment_scenarios: Sequence[tuple[float, float]],
                         features_as_of: datetime, prediction_at: datetime,
                         first_pitch: datetime, starters_confirmed: bool,
                         lineups_confirmed: bool, source_sha256: str, game_id: str) -> dict:
    """Scenarios are (weight, combined run factor), with weights summing to one.

    Source hash binds a caller-supplied PIT snapshot; it is not proof of its
    truth. No market price, total, external probability or fallback is consumed.
    """
    if not game_id or len(source_sha256) != 64 or any(c not in '0123456789abcdef' for c in source_sha256):
        raise ValueError("SOURCE_IDENTITY_REQUIRED")
    if not (aware(parameters.training_end) < aware(prediction_at)
            and aware(features_as_of) <= prediction_at < aware(first_pitch)):
        raise ValueError("PREGAME_PIT_REQUIRED")
    if starters_confirmed is not True or lineups_confirmed is not True:
        raise ValueError("CONFIRMED_STARTERS_AND_LINEUPS_REQUIRED")
    for lineup in (away_top3, home_top3):
        if len(lineup) != 3 or len({b.player_id for b in lineup}) != 3:
            raise ValueError("EXACT_TOP_THREE_REQUIRED")
    if set(b.player_id for b in away_top3) & set(b.player_id for b in home_top3):
        raise ValueError("LINEUP_IDENTITY_COLLISION")
    if away_pitcher.pitcher_id == home_pitcher.pitcher_id:
        raise ValueError("STARTER_IDENTITY_COLLISION")
    if not environment_scenarios:
        raise ValueError("ENVIRONMENT_SCENARIOS_REQUIRED")
    details = []
    for weight, factor in environment_scenarios:
        if finite(weight, 'weight') <= 0 or finite(factor, 'run_factor') <= 0:
            raise ValueError("INVALID_ENVIRONMENT_SCENARIO")
        top = _half(home_pitcher, away_top3, parameters, factor)
        bottom = _half(away_pitcher, home_top3, parameters, factor)
        details.append({"weight": weight, "run_factor": factor, "top": top, "bottom": bottom})
    if abs(sum(r['weight'] for r in details) - 1) > 1e-9:
        raise ValueError("SCENARIO_MASS_INVALID")
    nrfi = sum(r['weight'] * r['top']['hold_probability'] * r['bottom']['hold_probability']
               for r in details)
    identity = {"version": "first_inning_matchup_research_v1", "game_id": game_id,
                "source_sha256": source_sha256, "parameters": {**asdict(parameters),
                "training_end": parameters.training_end.isoformat()},
                "away_pitcher": asdict(away_pitcher), "home_pitcher": asdict(home_pitcher),
                "away_top3": [asdict(b) for b in away_top3],
                "home_top3": [asdict(b) for b in home_top3], "scenarios": details,
                "features_as_of": features_as_of.isoformat(),
                "prediction_at": prediction_at.isoformat(), "first_pitch": first_pitch.isoformat()}
    return {"research_probability": {"NRFI": nrfi, "YRFI": 1 - nrfi},
            "half_innings": details, "input_sha256": canonical_json_sha256(identity),
            "status": "RESEARCH_UNVALIDATED", "official_eligible": False,
            "promotion_authority": False, "stake": 0.0}
