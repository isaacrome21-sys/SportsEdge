"""Sport-specific state validation for LIVE_ENGINE_V1.

These adapters define what a predictive live model is allowed to consume. They
validate point-in-time game state; they do not fetch data and they do not create
probabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .live_engine import LiveEngineError, LiveGameState


@dataclass(frozen=True)
class AdapterResult:
    sport: str
    features: Mapping[str, Any]


class BaseLiveAdapter:
    sport: str
    required_state_fields: tuple[str, ...] = ()

    def transform(self, state: LiveGameState) -> AdapterResult:
        state.validate()
        if state.sport != self.sport:
            raise LiveEngineError(f"adapter {self.sport} cannot transform {state.sport}")
        missing = [name for name in self.required_state_fields if state.state.get(name) is None]
        if missing:
            raise LiveEngineError(f"missing live state fields: {', '.join(missing)}")
        features = {
            "home_score": state.home_score,
            "away_score": state.away_score,
            "score_margin_home": state.home_score - state.away_score,
            "clock_seconds": state.clock_seconds,
            "period": state.period,
            **dict(state.state),
        }
        return AdapterResult(self.sport, features)


class FootballLiveAdapter(BaseLiveAdapter):
    required_state_fields = (
        "down",
        "distance",
        "yardline_100",
        "timeouts_home",
        "timeouts_away",
        "plays_home",
        "plays_away",
    )

    def transform(self, state: LiveGameState) -> AdapterResult:
        result = super().transform(state)
        features = dict(result.features)
        if state.possession not in {"HOME", "AWAY", None}:
            raise LiveEngineError("football possession must be HOME, AWAY, or None")
        features["possession"] = state.possession
        return AdapterResult(self.sport, features)


class NFLLiveAdapter(FootballLiveAdapter):
    sport = "NFL"


class CFBLiveAdapter(FootballLiveAdapter):
    sport = "CFB"
    required_state_fields = FootballLiveAdapter.required_state_fields + (
        "home_pregame_rating",
        "away_pregame_rating",
    )


class MLBLiveAdapter(BaseLiveAdapter):
    sport = "MLB"
    required_state_fields = (
        "inning",
        "inning_half",
        "outs",
        "balls",
        "strikes",
        "bases_occupied",
        "batting_team",
        "home_pregame_rating",
        "away_pregame_rating",
    )

    def transform(self, state: LiveGameState) -> AdapterResult:
        result = super().transform(state)
        features = dict(result.features)
        inning = int(features["inning"])
        outs = int(features["outs"])
        balls = int(features["balls"])
        strikes = int(features["strikes"])
        if inning < 1:
            raise LiveEngineError("inning must be >= 1")
        if features["inning_half"] not in {"TOP", "BOTTOM"}:
            raise LiveEngineError("inning_half must be TOP or BOTTOM")
        if outs not in {0, 1, 2}:
            raise LiveEngineError("outs must be 0, 1, or 2")
        if not 0 <= balls <= 3 or not 0 <= strikes <= 2:
            raise LiveEngineError("invalid balls/strikes state")
        bases = features["bases_occupied"]
        if not isinstance(bases, (list, tuple)) or any(base not in {1, 2, 3} for base in bases):
            raise LiveEngineError("bases_occupied must contain only 1, 2, 3")
        return AdapterResult(self.sport, features)


ADAPTERS = {
    "MLB": MLBLiveAdapter(),
    "NFL": NFLLiveAdapter(),
    "CFB": CFBLiveAdapter(),
}


def adapter_for(sport: str) -> BaseLiveAdapter:
    try:
        return ADAPTERS[sport]
    except KeyError as exc:
        raise LiveEngineError(f"unsupported sport: {sport}") from exc
