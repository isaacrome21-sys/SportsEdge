"""Transparent NHL rate assembly for the shared goal engine.

Weights are configuration, not fitted defaults. Production callers must supply a
versioned parameter set learned only from PIT-safe training data.
"""
from dataclasses import dataclass
import math
from .features import NHLFeatureSnapshot
from .simulation import NHLGameState


@dataclass(frozen=True)
class NHLRateParameters:
    version: str
    intercept: float
    offense_xg: float
    opponent_xga: float
    shot_share: float
    special_teams: float
    goalie_gsax: float
    rest: float
    travel: float
    lineup: float
    home_ice: float

    def validate(self) -> None:
        if not self.version:
            raise ValueError("parameter version is required")
        values = self.__dict__.copy(); values.pop("version")
        if any(not math.isfinite(v) for v in values.values()):
            raise ValueError("all rate parameters must be finite")


def _linear_rate(team, opponent, opponent_goalie, p: NHLRateParameters, *, home: bool) -> float:
    shot_share = team.shots_for_per_60 / max(1e-9, team.shots_for_per_60 + opponent.shots_against_per_60)
    special = team.power_play_xg_per_60 + opponent.penalty_kill_xga_per_60
    rest_delta = team.rest_days - opponent.rest_days
    travel_delta = team.travel_km - opponent.travel_km
    eta = (p.intercept + p.offense_xg * team.xgf_per_60 + p.opponent_xga * opponent.xga_per_60
           + p.shot_share * shot_share + p.special_teams * special
           - p.goalie_gsax * opponent_goalie.goals_saved_above_expected_per_60
           + p.rest * rest_delta + p.travel * travel_delta
           + p.lineup * team.lineup_strength + (p.home_ice if home else 0.0))
    return math.exp(max(-8.0, min(4.0, eta)))


def game_state_from_snapshot(snapshot: NHLFeatureSnapshot, params: NHLRateParameters, *, home_ot_win_probability: float = 0.5) -> NHLGameState:
    snapshot.validate(); params.validate()
    if not 0 <= home_ot_win_probability <= 1:
        raise ValueError("home_ot_win_probability must be in [0, 1]")
    home_rate = _linear_rate(snapshot.home, snapshot.away, snapshot.away_goalie, params, home=True)
    away_rate = _linear_rate(snapshot.away, snapshot.home, snapshot.home_goalie, params, home=False)
    return NHLGameState(snapshot.game_id, home_rate, away_rate, home_ot_win_probability)
