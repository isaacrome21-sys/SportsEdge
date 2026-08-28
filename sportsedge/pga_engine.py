"""Joint full-field PGA tournament simulation and market readouts.

Tournament, finishing-position, FRL, make-cut and H2H markets are derived from
one coherent simulated field. The engine is intentionally sportsbook-independent
until the pricing helpers and does not claim trained predictive superiority.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from random import Random
from typing import Iterable, Mapping, Sequence

from .truth_gate import american_to_decimal


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
        if not str(self.player_id).strip() or not str(self.name).strip():
            raise ValueError("PGA_PLAYER_IDENTITY_REQUIRED")
        if not str(self.wave).strip():
            raise ValueError("PGA_WAVE_REQUIRED")
        for label, value in (
            ("sg_mean", self.sg_mean),
            ("sg_volatility", self.sg_volatility),
            ("course_fit", self.course_fit),
            ("blowup_rate", self.blowup_rate),
            ("right_tail_scale", self.right_tail_scale),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)):
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
    common_weather_sigma: float = 0.25
    tournament_form_sigma: float = 0.35

    def __post_init__(self) -> None:
        if isinstance(self.par, bool) or not isinstance(self.par, int) or self.par < 50 or self.par > 90:
            raise ValueError("PGA_PAR_INVALID")
        if isinstance(self.rounds, bool) or not isinstance(self.rounds, int):
            raise ValueError("PGA_ROUNDS_INVALID")
        if self.rounds < 2 or not 1 <= self.cut_after_round < self.rounds:
            raise ValueError("PGA_ROUND_CONTRACT_INVALID")
        if isinstance(self.cut_top_n, bool) or not isinstance(self.cut_top_n, int) or self.cut_top_n < 1:
            raise ValueError("PGA_CUT_TOP_N_INVALID")
        for label, value in (
            ("course_fit_weight", self.course_fit_weight),
            ("max_course_fit_weight", self.max_course_fit_weight),
            ("wave_weather_sigma", self.wave_weather_sigma),
            ("common_weather_sigma", self.common_weather_sigma),
            ("tournament_form_sigma", self.tournament_form_sigma),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)):
                raise ValueError(f"PGA_CONFIG_NONFINITE:{label}")
            if float(value) < 0:
                raise ValueError(f"PGA_CONFIG_NEGATIVE:{label}")
        if self.max_course_fit_weight > 1.0:
            raise ValueError("PGA_COURSE_FIT_CAP_IMPLAUSIBLE")


@dataclass(frozen=True)
class PGAPlayerTournamentPath:
    player_id: str
    name: str
    round_scores: tuple[int, ...]
    made_cut: bool
    cut_score: int
    total_score: int | None


@dataclass(frozen=True)
class PGATournamentPath:
    players: tuple[PGAPlayerTournamentPath, ...]
    cut_line: int
    weather_by_round_wave: Mapping[tuple[int, str], float]
    common_weather_by_round: Mapping[int, float]


def regularized_course_adjustment(player: PGAPlayer, config: PGATournamentConfig) -> float:
    weight = min(float(config.course_fit_weight), float(config.max_course_fit_weight))
    fit = max(-2.0, min(2.0, float(player.course_fit)))
    return weight * fit


def _sample_round_delta(rng: Random, player: PGAPlayer, effective_sg: float) -> float:
    delta = -effective_sg + rng.gauss(0.0, player.sg_volatility)
    if player.blowup_rate and rng.random() < player.blowup_rate:
        if player.right_tail_scale > 0:
            delta += rng.expovariate(1.0 / player.right_tail_scale)
    return delta


def dead_heat_payout_fraction(scores: Iterable[int], player_score: int, top_k: int) -> float:
    """Expected paid stake fraction for a top-K market under dead-heat splitting."""
    values = list(scores)
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1 or not values:
        return 0.0
    better = sum(score < player_score for score in values)
    tied = sum(score == player_score for score in values)
    if tied == 0 or better >= top_k:
        return 0.0
    return min(tied, top_k - better) / tied


def american_implied(odds: int | float) -> float:
    """Canonical SportsEdge American-odds validation plus raw implied probability."""
    return 1.0 / american_to_decimal(odds)


def n_way_devig(american_odds: Mapping[str, int | float]) -> tuple[dict[str, float], float]:
    if not isinstance(american_odds, Mapping) or len(american_odds) < 2:
        raise ValueError("PGA_NWAY_MARKET_REQUIRES_MULTIPLE_OUTCOMES")
    keys = [str(key).strip() for key in american_odds]
    if any(not key for key in keys) or len(set(keys)) != len(keys):
        raise ValueError("PGA_NWAY_OUTCOME_IDENTITY_INVALID")
    implied = {str(key): american_implied(odds) for key, odds in american_odds.items()}
    total = sum(implied.values())
    if not isfinite(total) or total <= 0:
        raise ValueError("PGA_NWAY_MARKET_INVALID")
    return {key: value / total for key, value in implied.items()}, total - 1.0


def dead_heat_expected_value(expected_paid_fraction: float, american_odds: int | float) -> float:
    """Net EV per $1 staked when a position market may be dead-heat reduced.

    A paid fraction f returns f * decimal_odds; the rest of the original stake is
    lost under standard dead-heat settlement, so net EV is E[f]*decimal - 1.
    """
    if isinstance(expected_paid_fraction, bool) or not isinstance(expected_paid_fraction, (int, float)):
        raise ValueError("PGA_DEAD_HEAT_FRACTION_INVALID")
    fraction = float(expected_paid_fraction)
    if not isfinite(fraction) or not 0.0 <= fraction <= 1.0:
        raise ValueError("PGA_DEAD_HEAT_FRACTION_INVALID")
    return fraction * american_to_decimal(american_odds) - 1.0


def _validate_field(players: Sequence[PGAPlayer]) -> None:
    if len(players) < 2:
        raise ValueError("PGA_FIELD_TOO_SMALL")
    ids = [player.player_id for player in players]
    if len(set(ids)) != len(ids):
        raise ValueError("PGA_DUPLICATE_PLAYER_ID")


def simulate_one_tournament(
    players: Iterable[PGAPlayer],
    *,
    config: PGATournamentConfig = PGATournamentConfig(),
    seed: int,
) -> PGATournamentPath:
    field = list(players)
    _validate_field(field)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("PGA_SEED_INVALID")
    rng = Random(seed)
    weather: dict[tuple[int, str], float] = {}
    common_weather: dict[int, float] = {}
    round_scores: dict[str, list[int]] = {player.player_id: [] for player in field}
    latent_form = {
        player.player_id: rng.gauss(0.0, config.tournament_form_sigma)
        for player in field
    }

    def play_round(round_number: int, active: Sequence[PGAPlayer]) -> None:
        common_weather[round_number] = rng.gauss(0.0, config.common_weather_sigma)
        waves = sorted({player.wave for player in active})
        for wave in waves:
            weather[(round_number, wave)] = rng.gauss(0.0, config.wave_weather_sigma)
        for player in active:
            effective_sg = (
                player.sg_mean
                + regularized_course_adjustment(player, config)
                + latent_form[player.player_id]
            )
            delta = (
                _sample_round_delta(rng, player, effective_sg)
                + common_weather[round_number]
                + weather[(round_number, player.wave)]
            )
            round_scores[player.player_id].append(int(round(config.par + delta)))

    for round_number in range(1, config.cut_after_round + 1):
        play_round(round_number, field)

    cut_totals = sorted(sum(round_scores[player.player_id]) for player in field)
    cut_index = min(config.cut_top_n, len(cut_totals)) - 1
    cut_line = cut_totals[cut_index]
    # PGA Tour standard is top N and ties, so a tied boundary can advance >N players.
    made_cut = {
        player.player_id: sum(round_scores[player.player_id]) <= cut_line
        for player in field
    }

    for round_number in range(config.cut_after_round + 1, config.rounds + 1):
        active = [player for player in field if made_cut[player.player_id]]
        play_round(round_number, active)

    paths: list[PGAPlayerTournamentPath] = []
    for player in field:
        scores = tuple(round_scores[player.player_id])
        cut_score = sum(scores[: config.cut_after_round])
        paths.append(PGAPlayerTournamentPath(
            player_id=player.player_id,
            name=player.name,
            round_scores=scores,
            made_cut=made_cut[player.player_id],
            cut_score=cut_score,
            total_score=sum(scores) if made_cut[player.player_id] else None,
        ))
    return PGATournamentPath(tuple(paths), cut_line, weather, common_weather)


def simulate_tournament_market_probabilities(
    players: Iterable[PGAPlayer],
    *,
    config: PGATournamentConfig = PGATournamentConfig(),
    simulations: int = 10_000,
    seed: int,
    position_k: tuple[int, ...] = (5, 10, 20),
) -> dict[str, dict[str, float]]:
    field = list(players)
    _validate_field(field)
    if isinstance(simulations, bool) or not isinstance(simulations, int) or simulations < 1:
        raise ValueError("PGA_SIMULATIONS_INVALID")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("PGA_SEED_INVALID")
    if not position_k or any(type(k) is not int or k < 1 for k in position_k) or len(set(position_k)) != len(position_k):
        raise ValueError("PGA_POSITION_K_INVALID")

    result = {
        player.player_id: {
            "outright_win_share": 0.0,
            "first_round_leader_share": 0.0,
            **{f"top_{k}_probability": 0.0 for k in position_k},
            **{f"top_{k}_dead_heat_payout": 0.0 for k in position_k},
            "make_cut_probability": 0.0,
        }
        for player in field
    }
    master = Random(seed)
    for _ in range(simulations):
        path = simulate_one_tournament(field, config=config, seed=master.randrange(0, 2**63))
        finishers = [row for row in path.players if row.total_score is not None]
        final_scores = [int(row.total_score) for row in finishers]
        best = min(final_scores)
        winners = [row for row in finishers if row.total_score == best]
        for winner in winners:
            result[winner.player_id]["outright_win_share"] += 1.0 / len(winners)

        first_round_best = min(row.round_scores[0] for row in path.players)
        frl = [row for row in path.players if row.round_scores[0] == first_round_best]
        for leader in frl:
            result[leader.player_id]["first_round_leader_share"] += 1.0 / len(frl)

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
                result[row.player_id][f"top_{k}_dead_heat_payout"] += dead_heat_payout_fraction(final_scores, score, k)

    for player_result in result.values():
        for key in player_result:
            player_result[key] /= simulations
    return result


def simulate_head_to_head_probabilities(
    players: Iterable[PGAPlayer],
    matchups: Iterable[tuple[str, str]],
    *,
    config: PGATournamentConfig = PGATournamentConfig(),
    simulations: int = 10_000,
    seed: int,
) -> dict[tuple[str, str], dict[str, float]]:
    """Tournament H2H readouts from the same joint tournament semantics.

    If one player makes the cut and the other misses, the made-cut player wins. If
    both miss, their cut-stage scores decide the matchup. Exact ties are pushes.
    """
    field = list(players)
    _validate_field(field)
    if isinstance(simulations, bool) or not isinstance(simulations, int) or simulations < 1:
        raise ValueError("PGA_SIMULATIONS_INVALID")
    ids = {player.player_id for player in field}
    pairs = list(matchups)
    if not pairs:
        raise ValueError("PGA_H2H_MATCHUPS_REQUIRED")
    for a, b in pairs:
        if a == b or a not in ids or b not in ids:
            raise ValueError("PGA_H2H_IDENTITY_INVALID")

    out = {pair: {"a_win": 0.0, "b_win": 0.0, "push": 0.0} for pair in pairs}
    master = Random(seed)
    for _ in range(simulations):
        path = simulate_one_tournament(field, config=config, seed=master.randrange(0, 2**63))
        rows = {row.player_id: row for row in path.players}
        for pair in pairs:
            a, b = rows[pair[0]], rows[pair[1]]
            if a.made_cut != b.made_cut:
                key = "a_win" if a.made_cut else "b_win"
            else:
                score_a = int(a.total_score) if a.total_score is not None else a.cut_score
                score_b = int(b.total_score) if b.total_score is not None else b.cut_score
                key = "a_win" if score_a < score_b else "b_win" if score_b < score_a else "push"
            out[pair][key] += 1.0
    for row in out.values():
        for key in row:
            row[key] /= simulations
    return out
