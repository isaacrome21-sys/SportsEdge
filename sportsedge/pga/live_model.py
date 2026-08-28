from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Dict, Iterable

import numpy as np


@dataclass(frozen=True)
class LiveWeights:
    """Conservative post-R1 live blend; coefficients remain evidence-gated."""

    long_term_skill: float = 0.40
    current_event_ball_striking: float = 0.25
    recent_form: float = 0.15
    course_fit: float = 0.08
    putting_scrambling_sustainability: float = 0.05
    weather_tee_wave: float = 0.04
    volatility_error_profile: float = 0.03

    def normalized(self) -> "LiveWeights":
        values = np.array([
            self.long_term_skill,
            self.current_event_ball_striking,
            self.recent_form,
            self.course_fit,
            self.putting_scrambling_sustainability,
            self.weather_tee_wave,
            self.volatility_error_profile,
        ], dtype=float)
        if not np.all(np.isfinite(values)) or np.any(values < 0):
            raise ValueError("PGA_LIVE_WEIGHTS_INVALID")
        total = float(values.sum())
        if total <= 0:
            raise ValueError("PGA_LIVE_WEIGHTS_NONPOSITIVE")
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
    wave: str = "A"
    approach_sg: float | None = None
    ott_sg: float | None = None
    putting_sg: float | None = None
    gir_rate: float | None = None
    fairway_rate: float | None = None
    penalty_strokes: float | None = None

    def __post_init__(self) -> None:
        if not str(self.player).strip() or not str(self.wave).strip():
            raise ValueError("PGA_LIVE_PLAYER_IDENTITY_REQUIRED")
        required = (
            self.leaderboard_strokes_to_par,
            self.long_term_sg,
            self.current_event_t2g_sg,
            self.recent_form_sg,
            self.course_fit_sg,
            self.putting_scrambling_sustainability_sg,
            self.weather_tee_wave_sg,
            self.volatility_error_profile_sg,
            self.round_sd,
        )
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(float(v)) for v in required):
            raise ValueError("PGA_LIVE_PLAYER_NONFINITE")
        if self.round_sd <= 0:
            raise ValueError("PGA_LIVE_ROUND_SD_INVALID")


@dataclass(frozen=True)
class TournamentSimulationResult:
    player: str
    win_prob: float
    top5_prob: float
    top10_prob: float
    top20_prob: float
    top5_dead_heat_payout: float
    top10_dead_heat_payout: float
    top20_dead_heat_payout: float
    expected_finish: float
    mean_final_strokes_to_par: float


@dataclass(frozen=True)
class TruthGateResult:
    passed: bool
    confidence_tier: str
    reasons: tuple[str, ...]


def _clip(value: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, float(value))))


def live_expected_sg_per_round(state: PlayerLiveState, weights: LiveWeights | None = None) -> float:
    """Blend durable skill with current-event information without letting noisy context dominate."""
    w = (weights or LiveWeights()).normalized()
    return float(
        w.long_term_skill * _clip(state.long_term_sg, -5.0, 5.0)
        + w.current_event_ball_striking * _clip(state.current_event_t2g_sg, -6.0, 6.0)
        + w.recent_form * _clip(state.recent_form_sg, -4.0, 4.0)
        + w.course_fit * _clip(state.course_fit_sg, -2.0, 2.0)
        + w.putting_scrambling_sustainability * _clip(state.putting_scrambling_sustainability_sg, -2.0, 2.0)
        + w.weather_tee_wave * _clip(state.weather_tee_wave_sg, -2.0, 2.0)
        + w.volatility_error_profile * _clip(state.volatility_error_profile_sg, -1.0, 1.0)
    )


def _effective_round_sd(state: PlayerLiveState) -> float:
    multiplier = 1.0 + _clip(state.volatility_error_profile_sg, -0.25, 0.35)
    return _clip(state.round_sd * multiplier, 1.6, 4.25)


def _dead_heat_fraction_for_rank(final_scores: np.ndarray, player_idx: int, top_k: int) -> np.ndarray:
    player_scores = final_scores[player_idx]
    better = np.sum(final_scores < player_scores[None, :], axis=0)
    tied = np.sum(final_scores == player_scores[None, :], axis=0)
    remaining = np.maximum(0, top_k - better)
    return np.where(better < top_k, np.minimum(tied, remaining) / tied, 0.0)


def simulate_remaining_tournament(
    players: Iterable[PlayerLiveState],
    rounds_remaining: int,
    n_sims: int = 100_000,
    seed: int = 20260820,
    common_round_sd: float = 0.25,
    wave_round_sd: float = 0.45,
    latent_form_sd: float = 0.30,
) -> Dict[str, TournamentSimulationResult]:
    """Joint live field simulation from the actual leaderboard.

    Each simulation carries persistent player form across remaining rounds, a
    common course-condition shock, and a tee-wave shock. Round scoring changes
    are discretized to strokes so ties/dead-heats remain real market outcomes.
    """
    states = list(players)
    if not states:
        return {}
    if len({state.player.casefold() for state in states}) != len(states):
        raise ValueError("PGA_LIVE_DUPLICATE_PLAYER")
    if type(rounds_remaining) is not int or rounds_remaining < 0:
        raise ValueError("PGA_LIVE_ROUNDS_REMAINING_INVALID")
    if type(n_sims) is not int or n_sims <= 0:
        raise ValueError("PGA_LIVE_SIMULATIONS_INVALID")
    if type(seed) is not int:
        raise ValueError("PGA_LIVE_SEED_INVALID")
    for label, value in (("common_round_sd", common_round_sd), ("wave_round_sd", wave_round_sd), ("latent_form_sd", latent_form_sd)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)) or float(value) < 0:
            raise ValueError(f"PGA_LIVE_{label.upper()}_INVALID")

    rng = np.random.default_rng(seed)
    n_players = len(states)
    start = np.array([state.leaderboard_strokes_to_par for state in states], dtype=float)
    final = np.repeat(start[:, None], n_sims, axis=1)
    latent_form = rng.normal(0.0, latent_form_sd, size=(n_players, n_sims))
    waves = sorted({state.wave for state in states})

    for _ in range(rounds_remaining):
        common = rng.normal(0.0, common_round_sd, size=n_sims)
        wave_shocks = {wave: rng.normal(0.0, wave_round_sd, size=n_sims) for wave in waves}
        for idx, state in enumerate(states):
            expected_sg = live_expected_sg_per_round(state) + latent_form[idx]
            player_noise = rng.normal(0.0, _effective_round_sd(state), size=n_sims)
            change = -expected_sg + common + wave_shocks[state.wave] + player_noise
            final[idx] += np.rint(change)

    # Share exact tournament ties rather than deleting them with a random epsilon.
    best = np.min(final, axis=0)
    winner_mask = final == best[None, :]
    winner_count = np.sum(winner_mask, axis=0)
    ranks = 1 + np.sum(final[:, None, :] < final[None, :, :], axis=0)

    out: Dict[str, TournamentSimulationResult] = {}
    for idx, state in enumerate(states):
        win_share = np.where(winner_mask[idx], 1.0 / winner_count, 0.0)
        rank = ranks[idx]
        top5_dh = _dead_heat_fraction_for_rank(final, idx, 5)
        top10_dh = _dead_heat_fraction_for_rank(final, idx, 10)
        top20_dh = _dead_heat_fraction_for_rank(final, idx, 20)
        out[state.player] = TournamentSimulationResult(
            player=state.player,
            win_prob=float(np.mean(win_share)),
            top5_prob=float(np.mean(rank <= 5)),
            top10_prob=float(np.mean(rank <= 10)),
            top20_prob=float(np.mean(rank <= 20)),
            top5_dead_heat_payout=float(np.mean(top5_dh)),
            top10_dead_heat_payout=float(np.mean(top10_dh)),
            top20_dead_heat_payout=float(np.mean(top20_dh)),
            expected_finish=float(np.mean(rank)),
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
    """PGA context gate; price/stake authorization remains in shared SportsEdge Truth Gate."""
    if any(type(v) is not bool for v in (has_shot_level_data, wd_status_verified, market_rules_verified)):
        raise ValueError("PGA_LIVE_GATE_BOOLEAN_INVALID")
    for label, value in (("edge", edge), ("expected_value", expected_value), ("min_edge", min_edge), ("min_ev", min_ev)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)):
            raise ValueError(f"PGA_LIVE_GATE_{label.upper()}_INVALID")
    if min_edge <= 0 or min_ev <= 0:
        raise ValueError("PGA_LIVE_GATE_THRESHOLDS_MUST_BE_POSITIVE")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("PGA_LIVE_GATE_NOW_TIMEZONE_REQUIRED")
    current = current.astimezone(timezone.utc)
    reasons: list[str] = []
    hard_fail = False

    def age_minutes(ts: datetime | None) -> float | None:
        if ts is None:
            return None
        if ts.tzinfo is None or ts.utcoffset() is None:
            raise ValueError("PGA_LIVE_SOURCE_TIMEZONE_REQUIRED")
        return max(0.0, (current - ts.astimezone(timezone.utc)).total_seconds() / 60.0)

    freshness = {
        "leaderboard": (leaderboard_timestamp, 5.0),
        "tee_times": (tee_time_timestamp, 720.0),
        "weather": (weather_timestamp, 60.0),
        "market": (market_timestamp, 10.0),
    }
    for label, (stamp, max_age) in freshness.items():
        age = age_minutes(stamp)
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
    if edge <= min_edge:
        hard_fail = True
        reasons.append(f"edge_below_gate:{edge:.4f}<={min_edge:.4f}")
    if expected_value <= min_ev:
        hard_fail = True
        reasons.append(f"ev_below_gate:{expected_value:.4f}<={min_ev:.4f}")

    confidence = "A"
    if not has_shot_level_data:
        confidence = "B"
        reasons.append("shot_level_missing_confidence_downgrade")
    return TruthGateResult(not hard_fail, confidence if not hard_fail else "NO_BET", tuple(reasons))
