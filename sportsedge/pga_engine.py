"""Joint full-field PGA tournament simulator foundation.

All tournament markets must be read-outs from the same simulated field. Weather is
sampled once per tee-time wave/round, the cut line is derived from the simulated
field, course fit is deliberately shrunk, and position-market value can use
expected dead-heat payout instead of raw top-K probability.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from random import Random
from typing import Iterable, Mapping


@dataclass(frozen=True)
class PGAPlayer:
    player_id: str
    name: str
    sg_mean: float
    sg_volatility: float
    course_fit: float = 0.0
    wave: str = "A"
    blowup_rate: float = 0.08
    right_tail_scale: float = 1.0

    def __post_init__(self) -> None:
        if not self.player_id or not self.name:
            raise ValueError("PGA_PLAYER_IDENTITY_REQUIRED")
        for label, value in (
            ("sg_mean", self.sg_mean), ("sg_volatility", self.sg_volatility),
            ("course_fit", self.course_fit), ("blowup_rate", self.blowup_rate),
            ("right_tail_scale", self.right_tail_scale),
        ):
            if not isfinite(float(value)):
                raise ValueError(f"PGA_PLAYER_NONFINITE:{label}")
        if self.sg_volatility < 0:
            raise ValueError("PGA_VOLATILITY_NEGATIVE")
        if not 0.0 <= self.blowup_rate <= 1.0:
            raise ValueError("PGA_BLOWUP_RATE_OUT_OF_RANGE")
        if self.right_tail_scale < 0:
            raise ValueError("PGA_RIGHT_TAIL_SCALE_NEGATIVE")


@dataclass(frozen=True)
class PGATournamentConfig:
    par: int = 72
    rounds: int = 4
    cut_after_round: int = 2
    cut_top_n: int = 65
    course_fit_weight: float = 0.15
    max_course_fit_weight: float = 0.20
    wave_weather_sigma: float = 0.70

    def __post_init__(self) -> None:
        if self.rounds < 2 or not 1 <= self.cut_after_round < self.rounds:
            raise ValueError("PGA_ROUND_CONTRACT_INVALID")
        if self.cut_top_n < 1:
            raise ValueError("PGA_CUT_TOP_N_INVALID")
        if self.wave_weather_sigma < 0:
            raise ValueError("PGA_WEATHER_SIGMA_NEGATIVE")
        if self.course_fit_weight < 0 or self.max_course_fit_weight < 0:
            raise ValueError("PGA_COURSE_FIT_WEIGHT_NEGATIVE")


@dataclass(frozen=True)
class PGAPlayerTournamentPath:
    player_id: str
    name: str
    round_scores: tuple[int, ...]
    made_cut: bool
    cut_score: int | None
    total_score: int | None


@dataclass(frozen=True)
class PGATournamentPath:
    players: tuple[PGAPlayerTournamentPath, ...]
    cut_line: int
    weather_by_round_wave: Mapping[tuple[int, str], float]


def regularized_course_adjustment(player: PGAPlayer, config: PGATournamentConfig) -> float:
    weight = min(config.course_fit_weight, config.max_course_fit_weight)
    fit = max(-2.0, min(2.0, float(player.course_fit)))
    return weight * fit


def _sample_round_delta(rng: Random, player: PGAPlayer, effective_sg: float) -> float:
    delta = -effective_sg + rng.gauss(0.0, player.sg_volatility)
    if player.blowup_rate and rng.random() < player.blowup_rate:
        delta += rng.expovariate(1.0 / max(1e-9, player.right_tail_scale))
    return delta


def dead_heat_payout_fraction(scores: Iterable[int], player_score: int, top_k: int) -> float:
    """Return the stake fraction paid under standard dead-heat splitting."""
    values = list(scores)
    if top_k < 1 or not values:
        return 0.0
    better = sum(score < player_score for score in values)
    tied = sum(score == player_score for score in values)
    if tied == 0 or better >= top_k:
        return 0.0
    paid_slots = min(tied, top_k - better)
    return paid_slots / tied


def american_implied(odds: int) -> float:
    if odds == 0:
        raise ValueError("PGA_ODDS_ZERO_INVALID")
    return 100.0 / (odds + 100.0) if odds > 0 else (-odds) / ((-odds) + 100.0)


def n_way_devig(american_odds: Mapping[str, int]) -> tuple[dict[str, float], float]:
    if len(american_odds) < 2:
        raise ValueError("PGA_NWAY_MARKET_REQUIRES_MULTIPLE_OUTCOMES")
    implied = {key: american_implied(int(odds)) for key, odds in american_odds.items()}
    total = sum(implied.values())
    if total <= 0:
        raise ValueError("PGA_NWAY_MARKET_INVALID")
    return {key: value / total for key, value in implied.items()}, total - 1.0


def simulate_one_tournament(
    players: Iterable[PGAPlayer],
    *,
    config: PGATournamentConfig = PGATournamentConfig(),
    seed: int,
) -> PGATournamentPath:
    field = list(players)
    if len(field) < 2:
        raise ValueError("PGA_FIELD_TOO_SMALL")
    if len({player.player_id for player in field}) != len(field):
        raise ValueError("PGA_DUPLICATE_PLAYER_ID")
    rng = Random(int(seed))
    weather: dict[tuple[int, str], float] = {}
    round_scores: dict[str, list[int]] = {player.player_id: [] for player in field}

    for round_number in range(1, config.cut_after_round + 1):
        for wave in {player.wave for player in field}:
            weather[(round_number, wave)] = rng.gauss(0.0, config.wave_weather_sigma)
        for player in field:
            effective_sg = player.sg_mean + regularized_course_adjustment(player, config)
            delta = _sample_round_delta(rng, player, effective_sg) + weather[(round_number, player.wave)]
            round_scores[player.player_id].append(int(round(config.par + delta)))

    cut_totals = sorted(sum(round_scores[player.player_id]) for player in field)
    cut_index = min(config.cut_top_n, len(cut_totals)) - 1
    cut_line = cut_totals[cut_index]
    made_cut = {player.player_id: sum(round_scores[player.player_id]) <= cut_line for player in field}

    for round_number in range(config.cut_after_round + 1, config.rounds + 1):
        active = [player for player in field if made_cut[player.player_id]]
        for wave in {player.wave for player in active}:
            weather[(round_number, wave)] = rng.gauss(0.0, config.wave_weather_sigma)
        for player in active:
            effective_sg = player.sg_mean + regularized_course_adjustment(player, config)
            delta = _sample_round_delta(rng, player, effective_sg) + weather[(round_number, player.wave)]
            round_scores[player.player_id].append(int(round(config.par + delta)))

    paths = []
    for player in field:
        scores = tuple(round_scores[player.player_id])
        paths.append(PGAPlayerTournamentPath(
            player_id=player.player_id,
            name=player.name,
            round_scores=scores,
            made_cut=made_cut[player.player_id],
            cut_score=sum(scores[: config.cut_after_round]),
            total_score=sum(scores) if made_cut[player.player_id] else None,
        ))
    return PGATournamentPath(tuple(paths), cut_line, weather)


def simulate_tournament_market_probabilities(
    players: Iterable[PGAPlayer],
    *,
    config: PGATournamentConfig = PGATournamentConfig(),
    simulations: int = 10_000,
    seed: int,
    position_k: tuple[int, ...] = (5, 10, 20),
) -> dict[str, dict[str, float]]:
    field = list(players)
    if simulations < 1:
        raise ValueError("PGA_SIMULATIONS_INVALID")
    result = {
        player.player_id: {
            "win_share": 0.0,
            **{f"top_{k}_probability": 0.0 for k in position_k},
            **{f"top_{k}_dead_heat_payout": 0.0 for k in position_k},
            "make_cut_probability": 0.0,
        }
        for player in field
    }
    master = Random(int(seed))
    for _ in range(simulations):
        path = simulate_one_tournament(field, config=config, seed=master.randrange(0, 2**63))
        finishers = [row for row in path.players if row.total_score is not None]
        final_scores = [int(row.total_score) for row in finishers]
        best = min(final_scores)
        winners = [row for row in finishers if row.total_score == best]
        for winner in winners:
            result[winner.player_id]["win_share"] += 1.0 / len(winners)
        for row in path.players:
            if row.made_cut:
                result[row.player_id]["make_cut_probability"] += 1.0
            if row.total_score is None:
                continue
            score = int(row.total_score)
            better = sum(other < score for other in final_scores)
            for k in position_k:
                if better < k:
                    result[row.player_id][f"top_{k}_probability"] += 1.0
                result[row.player_id][f"top_{k}_dead_heat_payout"] += dead_heat_payout_fraction(
                    final_scores, score, k
                )
    for player_result in result.values():
        for key in list(player_result):
            player_result[key] /= simulations
    return result
