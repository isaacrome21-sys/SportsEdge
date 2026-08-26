from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, Mapping

import numpy as np


@dataclass(frozen=True)
class LiveWeights:
    """Post-R1 live weighting agreed for PGA.

    The weights intentionally shift information away from speculative pre-event
    course fit and toward observed current-event ball striking while retaining a
    strong long-term prior.
    """

    long_term_skill: float = 0.40
    current_event_ball_striking: float = 0.25
    recent_form: float = 0.15
    course_fit: float = 0.08
    putting_scrambling_sustainability: float = 0.05
    weather_tee_wave: float = 0.04
    volatility_error_profile: float = 0.03

    def normalized(self) -> "LiveWeights":
        values = np.array(
            [
                self.long_term_skill,
                self.current_event_ball_striking,
                self.recent_form,
                self.course_fit,
                self.putting_scrambling_sustainability,
                self.weather_tee_wave,
                self.volatility_error_profile,
            ],
            dtype=float,
        )
        total = float(values.sum())
        if total <= 0:
            raise ValueError("Live weights must sum to a positive value")
        values /= total
        return LiveWeights(*map(float, values))


@dataclass(frozen=True)
class PlayerLiveState:
    player: str
    leaderboard_strokes_to_par: float
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


@dataclass(frozen=True)
class TournamentSimulationResult:
    player: str
    win_prob: float
    top5_prob: float
    top10_prob: float
    top20_prob: float
    expected_finish: float
    mean_final_strokes_to_par: float


@dataclass(frozen=True)
class TruthGateResult:
    passed: bool
    confidence_tier: str
    reasons: tuple[str, ...]


def live_expected_sg_per_round(
    state: PlayerLiveState,
    weights: LiveWeights | None = None,
) -> float:
    """Estimate remaining-round SG using the post-R1 live weighting.

    Positive SG means better than field average. Current-event T2G is preferred
    over raw score so hot/cold putting is not over-learned after one round.
    """

    w = (weights or LiveWeights()).normalized()
    return float(
        w.long_term_skill * state.long_term_sg
        + w.current_event_ball_striking * state.current_event_t2g_sg
        + w.recent_form * state.recent_form_sg
        + w.course_fit * state.course_fit_sg
        + w.putting_scrambling_sustainability
        * state.putting_scrambling_sustainability_sg
        + w.weather_tee_wave * state.weather_tee_wave_sg
        + w.volatility_error_profile * state.volatility_error_profile_sg
    )


def _effective_round_sd(state: PlayerLiveState) -> float:
    """Keep player-specific variance bounded but responsive to error profile."""

    # Error-profile feature changes spread, not mean. Positive values denote
    # elevated volatility. Bound the effect to avoid one-round explosions.
    multiplier = 1.0 + float(np.clip(state.volatility_error_profile_sg, -0.25, 0.35))
    return float(np.clip(state.round_sd * multiplier, 1.6, 4.25))


def simulate_remaining_tournament(
    players: Iterable[PlayerLiveState],
    rounds_remaining: int,
    n_sims: int = 100_000,
    seed: int = 20260820,
    shared_round_sd: float = 0.55,
) -> Dict[str, TournamentSimulationResult]:
    """Simulate a no-cut PGA field from the actual live leaderboard.

    The simulation preserves:
      * actual current leaderboard position,
      * player-specific expected SG and scoring variance,
      * shared round/course environment correlation.

    It intentionally does not invent cut logic because BMW Championship is a
    no-cut event.
    """

    states = list(players)
    if not states:
        return {}
    if rounds_remaining < 0:
        raise ValueError("rounds_remaining must be non-negative")
    if n_sims <= 0:
        raise ValueError("n_sims must be positive")

    rng = np.random.default_rng(seed)
    n_players = len(states)
    start = np.array([p.leaderboard_strokes_to_par for p in states], dtype=float)
    final = np.repeat(start[:, None], n_sims, axis=1)

    for _ in range(rounds_remaining):
        shared = rng.normal(0.0, shared_round_sd, size=n_sims)
        for idx, state in enumerate(states):
            # Positive SG improves score, so subtract it from strokes-to-par.
            expected_improvement = live_expected_sg_per_round(state)
            player_noise = rng.normal(0.0, _effective_round_sd(state), size=n_sims)
            final[idx] += -expected_improvement + shared + player_noise

    # Stable random tie-breaker avoids artificially splitting exact simulated ties.
    final_for_rank = final + rng.normal(0.0, 1e-7, size=final.shape)
    ranks = np.argsort(np.argsort(final_for_rank, axis=0), axis=0) + 1

    out: Dict[str, TournamentSimulationResult] = {}
    for idx, state in enumerate(states):
        r = ranks[idx]
        out[state.player] = TournamentSimulationResult(
            player=state.player,
            win_prob=float(np.mean(r == 1)),
            top5_prob=float(np.mean(r <= 5)),
            top10_prob=float(np.mean(r <= 10)),
            top20_prob=float(np.mean(r <= 20)),
            expected_finish=float(np.mean(r)),
            mean_final_strokes_to_par=float(np.mean(final[idx])),
        )
    return out


def evaluate_live_truth_gate(
    *,
    leaderboard_timestamp: datetime | None,
    tee_time_timestamp: datetime | None,
    weather_timestamp: datetime | None,
    market_timestamp: datetime | None,
    has_shot_level_data: bool,
    wd_status_verified: bool,
    market_rules_verified: bool,
    edge: float,
    expected_value: float,
    min_edge: float,
    min_ev: float,
    now: datetime | None = None,
) -> TruthGateResult:
    """PGA live Truth Gate with stale-vs-missing distinctions.

    If shot-level data are unavailable, a candidate may still pass but only at a
    downgraded confidence tier; missing critical live state, market, rules, or
    WD verification blocks promotion.
    """

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    reasons: list[str] = []
    hard_fail = False

    def _age_minutes(ts: datetime | None) -> float | None:
        if ts is None:
            return None
        stamp = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        return max(0.0, (current - stamp).total_seconds() / 60.0)

    # Source-specific freshness. These are conservative live defaults.
    freshness = {
        "leaderboard": (leaderboard_timestamp, 5.0),
        "tee_times": (tee_time_timestamp, 720.0),
        "weather": (weather_timestamp, 60.0),
        "market": (market_timestamp, 10.0),
    }
    for label, (ts, max_age) in freshness.items():
        age = _age_minutes(ts)
        if age is None:
            hard_fail = True
            reasons.append(f"missing_{label}")
        elif age > max_age:
            hard_fail = True
            reasons.append(f"stale_{label}:{age:.1f}m")

    if not wd_status_verified:
        hard_fail = True
        reasons.append("wd_status_unverified")
    if not market_rules_verified:
        hard_fail = True
        reasons.append("market_rules_unverified")
    if edge < min_edge:
        hard_fail = True
        reasons.append(f"edge_below_gate:{edge:.4f}<{min_edge:.4f}")
    if expected_value < min_ev:
        hard_fail = True
        reasons.append(f"ev_below_gate:{expected_value:.4f}<{min_ev:.4f}")

    confidence = "A"
    if not has_shot_level_data:
        reasons.append("shot_level_missing_confidence_downgrade")
        confidence = "B"

    if hard_fail:
        return TruthGateResult(False, "NO_BET", tuple(reasons))
    return TruthGateResult(True, confidence, tuple(reasons))
