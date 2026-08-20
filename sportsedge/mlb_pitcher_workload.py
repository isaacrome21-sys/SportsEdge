"""Pitcher workload controller for the shared MLB PA simulation path."""
from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Mapping


@dataclass(frozen=True)
class PitchCountDistribution:
    values: tuple[tuple[int, float], ...] = ((4, 1.0),)

    def __post_init__(self) -> None:
        if not self.values:
            raise ValueError("PITCH_COUNT_DISTRIBUTION_REQUIRED")
        if any(pitches < 1 or (not math.isfinite(prob)) or prob < 0.0 for pitches, prob in self.values):
            raise ValueError("PITCH_COUNT_DISTRIBUTION_INVALID")
        if not math.isclose(sum(prob for _, prob in self.values), 1.0, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("PITCH_COUNT_DISTRIBUTION_MUST_SUM_TO_ONE")

    def draw(self, rng: random.Random) -> int:
        u = rng.random()
        cumulative = 0.0
        for pitches, probability in self.values:
            cumulative += probability
            if u < cumulative:
                return pitches
        return self.values[-1][0]


@dataclass(frozen=True)
class PitcherWorkloadSpec:
    pitcher_id: str
    hard_bf_cap: int = 36
    hard_pitch_cap: int = 120
    min_bf_before_hazard: int = 999
    removal_hazard_after_pa: float = 0.0
    pitch_counts: PitchCountDistribution = PitchCountDistribution()

    def __post_init__(self) -> None:
        if not str(self.pitcher_id):
            raise ValueError("PITCHER_ID_REQUIRED")
        if self.hard_bf_cap < 1 or self.hard_pitch_cap < 1:
            raise ValueError("PITCHER_WORKLOAD_CAP_INVALID")
        if self.min_bf_before_hazard < 0:
            raise ValueError("PITCHER_MIN_BF_INVALID")
        if not 0.0 <= self.removal_hazard_after_pa <= 1.0:
            raise ValueError("PITCHER_REMOVAL_HAZARD_INVALID")


@dataclass(frozen=True)
class PitchingStaffConfig:
    pitchers: tuple[PitcherWorkloadSpec, ...]

    def __post_init__(self) -> None:
        if not self.pitchers:
            raise ValueError("PITCHING_STAFF_REQUIRED")
        ids = [p.pitcher_id for p in self.pitchers]
        if len(ids) != len(set(ids)):
            raise ValueError("DUPLICATE_PITCHER_IN_STAFF")


@dataclass
class _PitcherState:
    bf: int = 0
    pitches: int = 0
    outs: int = 0
    strikeouts: int = 0
    hits_allowed: int = 0
    walks: int = 0
    hbp: int = 0
    earned_runs: int = 0
    removed: bool = False
    bf_after_removal: int = 0


@dataclass(frozen=True)
class PitcherWorkloadSnapshot:
    pitcher_id: str
    bf: int
    pitches: int
    outs: int
    strikeouts: int
    hits_allowed: int
    walks: int
    hbp: int
    earned_runs: int
    removed: bool
    bf_after_removal: int

    @property
    def innings(self) -> float:
        return self.outs / 3.0


class PitcherWorkloadEngine:
    """Stateful path controller. Removal decisions happen only between PAs."""

    def __init__(self, staff: PitchingStaffConfig, rng: random.Random | None = None):
        self.staff = staff
        self.rng = rng or random.Random()
        self._index = 0
        self._state = {spec.pitcher_id: _PitcherState() for spec in staff.pitchers}

    def assign_pitcher(self) -> str:
        while self._index < len(self.staff.pitchers) and self._state[self.staff.pitchers[self._index].pitcher_id].removed:
            self._index += 1
        if self._index >= len(self.staff.pitchers):
            raise RuntimeError("PITCHING_STAFF_EXHAUSTED")
        return self.staff.pitchers[self._index].pitcher_id

    def _spec(self, pitcher_id: str) -> PitcherWorkloadSpec:
        for spec in self.staff.pitchers:
            if spec.pitcher_id == pitcher_id:
                return spec
        raise ValueError(f"PITCHER_NOT_IN_STAFF:{pitcher_id}")

    def record_pa(
        self,
        pitcher_id: str,
        *,
        outcome: str,
        outs: int,
        runs_charged: Mapping[str, int],
    ) -> None:
        current = self.assign_pitcher()
        state = self._state[pitcher_id]
        if pitcher_id != current or state.removed:
            state.bf_after_removal += 1
            raise ValueError(f"BF_AFTER_PITCHER_REMOVAL:{pitcher_id}")
        spec = self._spec(pitcher_id)
        state.bf += 1
        state.pitches += spec.pitch_counts.draw(self.rng)
        state.outs += outs
        if outcome == "K":
            state.strikeouts += 1
        elif outcome in {"1B", "2B", "3B", "HR"}:
            state.hits_allowed += 1
        elif outcome == "BB":
            state.walks += 1
        elif outcome == "HBP":
            state.hbp += 1

        for responsible_pitcher, runs in runs_charged.items():
            if responsible_pitcher in self._state:
                self._state[responsible_pitcher].earned_runs += int(runs)

        hit_hard_cap = state.bf >= spec.hard_bf_cap or state.pitches >= spec.hard_pitch_cap
        hazard_active = state.bf >= spec.min_bf_before_hazard and spec.removal_hazard_after_pa > 0.0
        hazard_remove = hazard_active and self.rng.random() < spec.removal_hazard_after_pa
        if hit_hard_cap or hazard_remove:
            state.removed = True
            self._index += 1

    def record_non_pa_out(self, pitcher_id: str, *, outs: int = 1) -> None:
        """Credit a defensive out (e.g. caught stealing) without adding BF."""
        if outs < 1:
            raise ValueError("NON_PA_OUT_MUST_BE_POSITIVE")
        current = self.assign_pitcher()
        state = self._state[pitcher_id]
        if pitcher_id != current or state.removed:
            raise ValueError(f"NON_PA_OUT_AFTER_PITCHER_REMOVAL:{pitcher_id}")
        state.outs += outs

    def snapshots(self) -> dict[str, PitcherWorkloadSnapshot]:
        return {
            pitcher_id: PitcherWorkloadSnapshot(
                pitcher_id=pitcher_id,
                bf=s.bf,
                pitches=s.pitches,
                outs=s.outs,
                strikeouts=s.strikeouts,
                hits_allowed=s.hits_allowed,
                walks=s.walks,
                hbp=s.hbp,
                earned_runs=s.earned_runs,
                removed=s.removed,
                bf_after_removal=s.bf_after_removal,
            )
            for pitcher_id, s in self._state.items()
        }
