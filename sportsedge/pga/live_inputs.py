from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Iterable, Mapping

from .live_model import PlayerLiveState


@dataclass(frozen=True)
class SourceStamp:
    source: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if not str(self.source).strip():
            raise ValueError("PGA_SOURCE_NAME_REQUIRED")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("PGA_SOURCE_TIMESTAMP_TIMEZONE_REQUIRED")


@dataclass(frozen=True)
class LiveGolferInput:
    player: str
    strokes_to_par: float
    long_term_sg: float
    current_event_t2g_sg: float
    recent_form_sg: float
    course_fit_sg: float
    putting_scrambling_sustainability_sg: float = 0.0
    weather_tee_wave_sg: float = 0.0
    volatility_error_profile_sg: float = 0.0
    round_sd: float = 2.65
    wave: str = "A"
    approach_sg: float | None = None
    ott_sg: float | None = None
    putting_sg: float | None = None
    gir_rate: float | None = None
    fairway_rate: float | None = None
    penalty_strokes: float | None = None

    def to_state(self) -> PlayerLiveState:
        return PlayerLiveState(
            player=self.player,
            leaderboard_strokes_to_par=float(self.strokes_to_par),
            long_term_sg=float(self.long_term_sg),
            current_event_t2g_sg=float(self.current_event_t2g_sg),
            recent_form_sg=float(self.recent_form_sg),
            course_fit_sg=float(self.course_fit_sg),
            putting_scrambling_sustainability_sg=float(self.putting_scrambling_sustainability_sg),
            weather_tee_wave_sg=float(self.weather_tee_wave_sg),
            volatility_error_profile_sg=float(self.volatility_error_profile_sg),
            round_sd=float(self.round_sd),
            wave=self.wave,
            approach_sg=self.approach_sg,
            ott_sg=self.ott_sg,
            putting_sg=self.putting_sg,
            gir_rate=self.gir_rate,
            fairway_rate=self.fairway_rate,
            penalty_strokes=self.penalty_strokes,
        )


@dataclass(frozen=True)
class LiveTournamentSnapshot:
    event: str
    round_number: int
    rounds_remaining: int
    is_no_cut: bool
    leaderboard_stamp: SourceStamp
    tee_times_stamp: SourceStamp
    weather_stamp: SourceStamp
    market_stamp: SourceStamp
    wd_status_verified: bool
    market_rules_verified: bool
    golfers: tuple[LiveGolferInput, ...]

    def __post_init__(self) -> None:
        if not str(self.event).strip():
            raise ValueError("PGA_EVENT_REQUIRED")
        if type(self.round_number) is not int or not 1 <= self.round_number <= 4:
            raise ValueError("PGA_ROUND_NUMBER_INVALID")
        if type(self.rounds_remaining) is not int or not 0 <= self.rounds_remaining <= 4:
            raise ValueError("PGA_ROUNDS_REMAINING_INVALID")
        if any(type(value) is not bool for value in (self.is_no_cut, self.wd_status_verified, self.market_rules_verified)):
            raise ValueError("PGA_SNAPSHOT_BOOLEAN_INVALID")
        if not self.golfers:
            raise ValueError("PGA_SNAPSHOT_GOLFERS_REQUIRED")
        names = [golfer.player.casefold() for golfer in self.golfers]
        if len(set(names)) != len(names):
            raise ValueError("PGA_SNAPSHOT_DUPLICATE_GOLFER")

    def player_states(self) -> tuple[PlayerLiveState, ...]:
        return tuple(golfer.to_state() for golfer in self.golfers)


def _required_float(row: Mapping[str, object], key: str, idx: int) -> float:
    try:
        value = float(row[key])
    except Exception as exc:
        raise ValueError(f"row {idx} invalid {key}") from exc
    if not isfinite(value):
        raise ValueError(f"row {idx} nonfinite {key}")
    return value


def _optional_float(value: object | None, *, label: str) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except Exception as exc:
        raise ValueError(f"invalid optional PGA field: {label}") from exc
    if not isfinite(out):
        raise ValueError(f"nonfinite optional PGA field: {label}")
    return out


def build_golfer_inputs(rows: Iterable[Mapping[str, object]]) -> tuple[LiveGolferInput, ...]:
    """Convert normalized provider rows into typed, provider-neutral live inputs."""
    out: list[LiveGolferInput] = []
    required = {
        "player", "strokes_to_par", "long_term_sg", "current_event_t2g_sg",
        "recent_form_sg", "course_fit_sg",
    }
    for idx, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError(f"row {idx} must be a mapping")
        missing = sorted(required.difference(row.keys()))
        if missing:
            raise ValueError(f"row {idx} missing required fields: {', '.join(missing)}")
        player = str(row["player"]).strip()
        if not player:
            raise ValueError(f"row {idx} missing player identity")
        out.append(LiveGolferInput(
            player=player,
            strokes_to_par=_required_float(row, "strokes_to_par", idx),
            long_term_sg=_required_float(row, "long_term_sg", idx),
            current_event_t2g_sg=_required_float(row, "current_event_t2g_sg", idx),
            recent_form_sg=_required_float(row, "recent_form_sg", idx),
            course_fit_sg=_required_float(row, "course_fit_sg", idx),
            putting_scrambling_sustainability_sg=float(row.get("putting_scrambling_sustainability_sg", 0.0)),
            weather_tee_wave_sg=float(row.get("weather_tee_wave_sg", 0.0)),
            volatility_error_profile_sg=float(row.get("volatility_error_profile_sg", 0.0)),
            round_sd=float(row.get("round_sd", 2.65)),
            wave=str(row.get("wave", "A")).strip() or "A",
            approach_sg=_optional_float(row.get("approach_sg"), label="approach_sg"),
            ott_sg=_optional_float(row.get("ott_sg"), label="ott_sg"),
            putting_sg=_optional_float(row.get("putting_sg"), label="putting_sg"),
            gir_rate=_optional_float(row.get("gir_rate"), label="gir_rate"),
            fairway_rate=_optional_float(row.get("fairway_rate"), label="fairway_rate"),
            penalty_strokes=_optional_float(row.get("penalty_strokes"), label="penalty_strokes"),
        ))
    if not out:
        raise ValueError("PGA_GOLFER_INPUTS_REQUIRED")
    names = [golfer.player.casefold() for golfer in out]
    if len(set(names)) != len(names):
        raise ValueError("PGA_DUPLICATE_GOLFER_INPUT")
    return tuple(out)
