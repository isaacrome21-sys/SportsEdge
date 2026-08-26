from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping

from .live_model import PlayerLiveState


@dataclass(frozen=True)
class SourceStamp:
    source: str
    observed_at: datetime


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
            putting_scrambling_sustainability_sg=float(
                self.putting_scrambling_sustainability_sg
            ),
            weather_tee_wave_sg=float(self.weather_tee_wave_sg),
            volatility_error_profile_sg=float(self.volatility_error_profile_sg),
            round_sd=float(self.round_sd),
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

    def player_states(self) -> tuple[PlayerLiveState, ...]:
        return tuple(g.to_state() for g in self.golfers)


def build_golfer_inputs(rows: Iterable[Mapping[str, object]]) -> tuple[LiveGolferInput, ...]:
    """Convert normalized provider rows into typed PGA live inputs.

    Provider-specific HTTP/API parsing belongs outside this function. Keeping
    the core adapter provider-neutral prevents sportsbook, leaderboard, and
    stats vendors from leaking their schemas into the model layer.
    """
    out: list[LiveGolferInput] = []
    required = {
        "player",
        "strokes_to_par",
        "long_term_sg",
        "current_event_t2g_sg",
        "recent_form_sg",
        "course_fit_sg",
    }
    for idx, row in enumerate(rows):
        missing = sorted(required.difference(row.keys()))
        if missing:
            raise ValueError(f"row {idx} missing required fields: {', '.join(missing)}")
        out.append(
            LiveGolferInput(
                player=str(row["player"]),
                strokes_to_par=float(row["strokes_to_par"]),
                long_term_sg=float(row["long_term_sg"]),
                current_event_t2g_sg=float(row["current_event_t2g_sg"]),
                recent_form_sg=float(row["recent_form_sg"]),
                course_fit_sg=float(row["course_fit_sg"]),
                putting_scrambling_sustainability_sg=float(
                    row.get("putting_scrambling_sustainability_sg", 0.0)
                ),
                weather_tee_wave_sg=float(row.get("weather_tee_wave_sg", 0.0)),
                volatility_error_profile_sg=float(
                    row.get("volatility_error_profile_sg", 0.0)
                ),
                round_sd=float(row.get("round_sd", 2.65)),
                approach_sg=_optional_float(row.get("approach_sg")),
                ott_sg=_optional_float(row.get("ott_sg")),
                putting_sg=_optional_float(row.get("putting_sg")),
                gir_rate=_optional_float(row.get("gir_rate")),
                fairway_rate=_optional_float(row.get("fairway_rate")),
                penalty_strokes=_optional_float(row.get("penalty_strokes")),
            )
        )
    return tuple(out)


def _optional_float(value: object | None) -> float | None:
    return None if value is None else float(value)
