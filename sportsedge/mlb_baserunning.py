"""Baserunning and stolen-base controller for shared MLB simulation paths."""
from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Mapping


@dataclass(frozen=True)
class BaserunningProfile:
    player_id: str
    attempt_second: float = 0.0
    success_second: float = 0.0
    attempt_third: float = 0.0
    success_third: float = 0.0

    def __post_init__(self) -> None:
        if not str(self.player_id):
            raise ValueError("BASERUNNER_ID_REQUIRED")
        for value in (self.attempt_second, self.success_second, self.attempt_third, self.success_third):
            if (not math.isfinite(value)) or not 0.0 <= value <= 1.0:
                raise ValueError("BASERUNNING_PROBABILITY_OUT_OF_RANGE")


@dataclass(frozen=True)
class BaserunningConfig:
    profiles: tuple[BaserunningProfile, ...]
    pitcher_attempt_multipliers: Mapping[str, float] | None = None
    catcher_success_multipliers: Mapping[str, float] | None = None

    def __post_init__(self) -> None:
        ids = [p.player_id for p in self.profiles]
        if len(ids) != len(set(ids)):
            raise ValueError("DUPLICATE_BASERUNNING_PROFILE")
        for mapping in (self.pitcher_attempt_multipliers or {}, self.catcher_success_multipliers or {}):
            for value in mapping.values():
                if (not math.isfinite(float(value))) or float(value) < 0.0:
                    raise ValueError("BASERUNNING_MULTIPLIER_INVALID")


@dataclass(frozen=True)
class BaserunningDecision:
    runner_id: str
    from_base: int
    to_base: int
    success: bool


class BaserunningEngine:
    def __init__(self, config: BaserunningConfig, rng: random.Random | None = None):
        self.config = config
        self.rng = rng or random.Random()
        self._profiles = {p.player_id: p for p in config.profiles}

    def maybe_attempt(
        self,
        *,
        bases: list,
        pitcher_id: str | None = None,
        catcher_id: str | None = None,
        outs: int,
        score_diff: int = 0,
    ) -> BaserunningDecision | None:
        if outs >= 3:
            return None
        # Lead runner first so no attempt can move into an occupied destination.
        for from_idx, to_idx in ((1, 2), (0, 1)):
            runner = bases[from_idx]
            if runner is None or bases[to_idx] is not None:
                continue
            profile = self._profiles.get(runner.player_id)
            if profile is None:
                continue
            if to_idx == 1:
                attempt_p, success_p = profile.attempt_second, profile.success_second
            else:
                attempt_p, success_p = profile.attempt_third, profile.success_third
            if pitcher_id is not None:
                attempt_p *= float((self.config.pitcher_attempt_multipliers or {}).get(pitcher_id, 1.0))
            if catcher_id is not None:
                success_p *= float((self.config.catcher_success_multipliers or {}).get(catcher_id, 1.0))
            attempt_p = min(max(attempt_p, 0.0), 1.0)
            success_p = min(max(success_p, 0.0), 1.0)
            if self.rng.random() >= attempt_p:
                continue
            return BaserunningDecision(
                runner_id=runner.player_id,
                from_base=from_idx + 1,
                to_base=to_idx + 1,
                success=self.rng.random() < success_p,
            )
        return None
