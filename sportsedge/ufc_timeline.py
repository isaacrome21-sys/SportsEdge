"""Competing-risks UFC timeline simulator.

Terminal KO/TKO and submission hazards, nonterminal strike/takedown/control events,
and decision outcomes live on one seeded path. Style is modeled as a pairwise
interaction and offensive/defensive cardio decay are separate parameters.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, log
from random import Random
from typing import Mapping


@dataclass(frozen=True)
class UFCFighterTimelineProfile:
    fighter_id: str
    name: str
    ko_hazard_per_min: float
    sub_hazard_per_min: float
    sig_strikes_landed_per_min: float
    takedown_attempts_per_min: float
    takedown_accuracy: float
    control_seconds_per_min: float
    offense_cardio_decay_per_round: float = 0.04
    defense_cardio_decay_per_round: float = 0.05
    style_pressure: float = 0.0
    style_counter: float = 0.0
    style_grappling: float = 0.0
    style_scramble: float = 0.0

    def __post_init__(self) -> None:
        if not self.fighter_id or not self.name:
            raise ValueError("UFC_TIMELINE_IDENTITY_REQUIRED")
        numeric = (
            self.ko_hazard_per_min,
            self.sub_hazard_per_min,
            self.sig_strikes_landed_per_min,
            self.takedown_attempts_per_min,
            self.takedown_accuracy,
            self.control_seconds_per_min,
            self.offense_cardio_decay_per_round,
            self.defense_cardio_decay_per_round,
            self.style_pressure,
            self.style_counter,
            self.style_grappling,
            self.style_scramble,
        )
        if not all(isfinite(float(value)) for value in numeric):
            raise ValueError("UFC_TIMELINE_NONFINITE")
        if min(
            self.ko_hazard_per_min,
            self.sub_hazard_per_min,
            self.sig_strikes_landed_per_min,
            self.takedown_attempts_per_min,
            self.control_seconds_per_min,
            self.offense_cardio_decay_per_round,
            self.defense_cardio_decay_per_round,
        ) < 0:
            raise ValueError("UFC_TIMELINE_NEGATIVE_RATE")
        if not 0.0 <= self.takedown_accuracy <= 1.0:
            raise ValueError("UFC_TIMELINE_TD_ACCURACY_RANGE")


@dataclass(frozen=True)
class UFCFightTimelinePath:
    fighter_a_id: str
    fighter_b_id: str
    winner_id: str
    outcome: str
    elapsed_seconds: float
    a_sig_strikes: int
    b_sig_strikes: int
    a_takedowns: int
    b_takedowns: int
    a_control_seconds: float
    b_control_seconds: float

    @property
    def went_to_decision(self) -> bool:
        return self.outcome == "DECISION"


@dataclass(frozen=True)
class UFCEffectiveRates:
    ko_hazard_per_min: float
    sub_hazard_per_min: float
    sig_strikes_per_min: float
    takedown_attempts_per_min: float
    takedown_accuracy: float
    control_seconds_per_min: float


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, value))


def pairwise_style_multipliers(
    attacker: UFCFighterTimelineProfile,
    defender: UFCFighterTimelineProfile,
) -> tuple[float, float]:
    striking = _clamp(
        1.0 + 0.12 * (attacker.style_pressure - defender.style_counter),
        0.65,
        1.35,
    )
    grappling = _clamp(
        1.0 + 0.12 * (attacker.style_grappling - defender.style_scramble),
        0.65,
        1.35,
    )
    return striking, grappling


def effective_rates(
    attacker: UFCFighterTimelineProfile,
    defender: UFCFighterTimelineProfile,
    *,
    elapsed_seconds: float,
) -> UFCEffectiveRates:
    rounds_elapsed = max(0.0, elapsed_seconds / 300.0)
    attacker_offense = exp(-attacker.offense_cardio_decay_per_round * rounds_elapsed)
    defender_defense = exp(-defender.defense_cardio_decay_per_round * rounds_elapsed)
    vulnerability = 1.0 / max(0.35, defender_defense)
    striking_style, grappling_style = pairwise_style_multipliers(attacker, defender)
    strike_mult = attacker_offense * vulnerability * striking_style
    grapple_mult = attacker_offense * vulnerability * grappling_style
    return UFCEffectiveRates(
        ko_hazard_per_min=max(0.0, attacker.ko_hazard_per_min * strike_mult),
        sub_hazard_per_min=max(0.0, attacker.sub_hazard_per_min * grapple_mult),
        sig_strikes_per_min=max(0.0, attacker.sig_strikes_landed_per_min * strike_mult),
        takedown_attempts_per_min=max(0.0, attacker.takedown_attempts_per_min * grapple_mult),
        takedown_accuracy=_clamp(attacker.takedown_accuracy * grapple_mult, 0.0, 1.0),
        control_seconds_per_min=max(0.0, attacker.control_seconds_per_min * grapple_mult),
    )


def _poisson(rng: Random, mean: float) -> int:
    if mean <= 0:
        return 0
    if mean > 20:
        return max(0, int(round(rng.gauss(mean, mean ** 0.5))))
    limit = exp(-mean)
    product = 1.0
    count = 0
    while product > limit:
        count += 1
        product *= rng.random()
    return count - 1


def _binomial(rng: Random, attempts: int, probability: float) -> int:
    return sum(rng.random() < probability for _ in range(max(0, attempts)))


def _accumulate_nonterminal(
    rng: Random,
    rates: UFCEffectiveRates,
    duration_seconds: float,
) -> tuple[int, int, float]:
    minutes = max(0.0, duration_seconds) / 60.0
    strikes = _poisson(rng, rates.sig_strikes_per_min * minutes)
    attempts = _poisson(rng, rates.takedown_attempts_per_min * minutes)
    takedowns = _binomial(rng, attempts, rates.takedown_accuracy)
    control = min(duration_seconds, rates.control_seconds_per_min * minutes)
    return strikes, takedowns, control


def simulate_fight_timeline(
    fighter_a: UFCFighterTimelineProfile,
    fighter_b: UFCFighterTimelineProfile,
    *,
    rounds: int = 3,
    step_seconds: float = 5.0,
    seed: int,
) -> UFCFightTimelinePath:
    if rounds not in {3, 5}:
        raise ValueError("UFC_TIMELINE_ROUNDS_UNSUPPORTED")
    if step_seconds <= 0 or step_seconds > 30:
        raise ValueError("UFC_TIMELINE_STEP_INVALID")
    if fighter_a.fighter_id == fighter_b.fighter_id:
        raise ValueError("UFC_TIMELINE_FIGHTER_IDS_MUST_DIFFER")
    rng = Random(int(seed))
    scheduled = float(rounds * 300)
    elapsed = 0.0
    a_ss = b_ss = a_td = b_td = 0
    a_ctrl = b_ctrl = 0.0

    while elapsed < scheduled:
        step = min(step_seconds, scheduled - elapsed)
        a_rates = effective_rates(fighter_a, fighter_b, elapsed_seconds=elapsed)
        b_rates = effective_rates(fighter_b, fighter_a, elapsed_seconds=elapsed)
        hazards = (
            ("A_KO", a_rates.ko_hazard_per_min),
            ("A_SUB", a_rates.sub_hazard_per_min),
            ("B_KO", b_rates.ko_hazard_per_min),
            ("B_SUB", b_rates.sub_hazard_per_min),
        )
        total_hazard = sum(rate for _, rate in hazards)
        event = None
        active_seconds = step
        if total_hazard > 0:
            wait_minutes = -log(max(1e-15, 1.0 - rng.random())) / total_hazard
            wait_seconds = wait_minutes * 60.0
            if wait_seconds < step:
                active_seconds = wait_seconds
                choice = rng.random() * total_hazard
                running = 0.0
                for label, rate in hazards:
                    running += rate
                    if choice <= running:
                        event = label
                        break

        x, y, z = _accumulate_nonterminal(rng, a_rates, active_seconds)
        a_ss += x
        a_td += y
        a_ctrl += z
        x, y, z = _accumulate_nonterminal(rng, b_rates, active_seconds)
        b_ss += x
        b_td += y
        b_ctrl += z
        elapsed += active_seconds

        if event is not None:
            winner = fighter_a.fighter_id if event.startswith("A_") else fighter_b.fighter_id
            outcome = "KO_TKO" if event.endswith("KO") else "SUBMISSION"
            return UFCFightTimelinePath(
                fighter_a.fighter_id,
                fighter_b.fighter_id,
                winner,
                outcome,
                elapsed,
                a_ss,
                b_ss,
                a_td,
                b_td,
                a_ctrl,
                b_ctrl,
            )

    a_score = a_ss + 2.5 * a_td + a_ctrl / 30.0
    b_score = b_ss + 2.5 * b_td + b_ctrl / 30.0
    if a_score == b_score:
        winner = fighter_a.fighter_id if rng.random() < 0.5 else fighter_b.fighter_id
    else:
        winner = fighter_a.fighter_id if a_score > b_score else fighter_b.fighter_id
    return UFCFightTimelinePath(
        fighter_a.fighter_id,
        fighter_b.fighter_id,
        winner,
        "DECISION",
        scheduled,
        a_ss,
        b_ss,
        a_td,
        b_td,
        a_ctrl,
        b_ctrl,
    )


def simulate_fight_distribution(
    fighter_a: UFCFighterTimelineProfile,
    fighter_b: UFCFighterTimelineProfile,
    *,
    rounds: int = 3,
    simulations: int = 25_000,
    seed: int,
) -> dict[str, float]:
    if simulations < 1:
        raise ValueError("UFC_TIMELINE_SIMULATIONS_INVALID")
    rng = Random(int(seed))
    counts = {
        "a_win": 0.0,
        "b_win": 0.0,
        "a_ko_tko": 0.0,
        "a_submission": 0.0,
        "a_decision": 0.0,
        "b_ko_tko": 0.0,
        "b_submission": 0.0,
        "b_decision": 0.0,
        "goes_distance": 0.0,
        "a_sig_strikes_mean": 0.0,
        "b_sig_strikes_mean": 0.0,
        "a_takedowns_mean": 0.0,
        "b_takedowns_mean": 0.0,
        "a_control_seconds_mean": 0.0,
        "b_control_seconds_mean": 0.0,
    }
    for _ in range(simulations):
        path = simulate_fight_timeline(
            fighter_a,
            fighter_b,
            rounds=rounds,
            seed=rng.randrange(0, 2**63),
        )
        a_won = path.winner_id == fighter_a.fighter_id
        counts["a_win" if a_won else "b_win"] += 1
        side = "a" if a_won else "b"
        method = (
            "ko_tko"
            if path.outcome == "KO_TKO"
            else "submission"
            if path.outcome == "SUBMISSION"
            else "decision"
        )
        counts[f"{side}_{method}"] += 1
        if path.went_to_decision:
            counts["goes_distance"] += 1
        counts["a_sig_strikes_mean"] += path.a_sig_strikes
        counts["b_sig_strikes_mean"] += path.b_sig_strikes
        counts["a_takedowns_mean"] += path.a_takedowns
        counts["b_takedowns_mean"] += path.b_takedowns
        counts["a_control_seconds_mean"] += path.a_control_seconds
        counts["b_control_seconds_mean"] += path.b_control_seconds
    return {key: value / simulations for key, value in counts.items()}


def american_implied(odds: int) -> float:
    if odds == 0:
        raise ValueError("UFC_ODDS_ZERO_INVALID")
    return 100.0 / (odds + 100.0) if odds > 0 else (-odds) / ((-odds) + 100.0)


def n_way_devig(american_odds: Mapping[str, int]) -> tuple[dict[str, float], float]:
    if len(american_odds) < 2:
        raise ValueError("UFC_NWAY_REQUIRES_MULTIPLE_OUTCOMES")
    implied = {key: american_implied(int(value)) for key, value in american_odds.items()}
    total = sum(implied.values())
    if total <= 0:
        raise ValueError("UFC_NWAY_INVALID")
    return {key: value / total for key, value in implied.items()}, total - 1.0
