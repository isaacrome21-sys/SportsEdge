"""SportsEdge UFC betting engine.

Clean-room production foundation for pre-fight UFC modeling.
The engine is intentionally sportsbook-independent until the pricing layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, log
from random import Random
from typing import Dict, Iterable, List, Mapping, Optional

from .truth_gate import TruthGateError, american_to_decimal


@dataclass(frozen=True)
class FighterSnapshot:
    name: str
    age: float
    height_in: float
    reach_in: float
    stance: str
    wins: int
    losses: int
    draws: int = 0
    sig_strikes_landed_pm: float = 0.0
    sig_strikes_absorbed_pm: float = 0.0
    sig_strike_accuracy: float = 0.0
    sig_strike_defense: float = 0.0
    takedowns_per_15: float = 0.0
    takedown_accuracy: float = 0.0
    takedown_defense: float = 0.0
    submissions_per_15: float = 0.0
    control_seconds_per_15: float = 0.0
    knockdowns_per_15: float = 0.0
    finish_win_rate: float = 0.0
    finish_loss_rate: float = 0.0
    recent_win_rate: float = 0.5
    strength_of_schedule: float = 0.5
    elo: float = 1500.0
    days_since_last_fight: float = 180.0
    weight_class: str = ""
    late_replacement: bool = False
    missingness: float = 0.0


@dataclass(frozen=True)
class FightContext:
    rounds: int = 3
    title_fight: bool = False
    short_notice_days: Optional[int] = None
    altitude_ft: float = 0.0


@dataclass(frozen=True)
class FightProjection:
    fighter_a: str
    fighter_b: str
    p_a_win: float
    p_b_win: float
    p_goes_distance: float
    p_inside_distance: float
    p_a_ko: float
    p_a_sub: float
    p_a_dec: float
    p_b_ko: float
    p_b_sub: float
    p_b_dec: float
    uncertainty: float


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + exp(-x))


def _safe(v: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, v))


def _probability(value: float, name: str, *, open_interval: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)):
        raise ValueError(f"{name} must be finite numeric")
    out = float(value)
    valid = 0.0 < out < 1.0 if open_interval else 0.0 <= out <= 1.0
    if not valid:
        bounds = "(0,1)" if open_interval else "[0,1]"
        raise ValueError(f"{name} must be in {bounds}")
    return out


def _feature_score(a: FighterSnapshot, b: FighterSnapshot, ctx: FightContext) -> float:
    """Interpretable sportsbook-independent baseline score.

    This is not a claimed trained model. It provides a deterministic challenger
    prior until historical walk-forward training artifacts are fitted.
    """
    striking = (
        0.12 * (a.sig_strikes_landed_pm - b.sig_strikes_landed_pm)
        - 0.10 * (a.sig_strikes_absorbed_pm - b.sig_strikes_absorbed_pm)
        + 0.90 * (a.sig_strike_accuracy - b.sig_strike_accuracy)
        + 0.90 * (a.sig_strike_defense - b.sig_strike_defense)
        + 0.06 * (a.knockdowns_per_15 - b.knockdowns_per_15)
    )
    grappling = (
        0.07 * (a.takedowns_per_15 - b.takedowns_per_15)
        + 0.70 * (a.takedown_accuracy - b.takedown_accuracy)
        + 0.85 * (a.takedown_defense - b.takedown_defense)
        + 0.10 * (a.submissions_per_15 - b.submissions_per_15)
        + 0.0008 * (a.control_seconds_per_15 - b.control_seconds_per_15)
    )
    physical = (
        0.025 * (a.reach_in - b.reach_in)
        + 0.015 * (a.height_in - b.height_in)
        - 0.025 * (a.age - b.age)
    )
    history = (
        0.0026 * (a.elo - b.elo)
        + 0.55 * (a.recent_win_rate - b.recent_win_rate)
        + 0.60 * (a.strength_of_schedule - b.strength_of_schedule)
        + 0.20 * (a.finish_win_rate - b.finish_win_rate)
        - 0.20 * (a.finish_loss_rate - b.finish_loss_rate)
    )
    rest = -0.0008 * abs(a.days_since_last_fight - 180.0) + 0.0008 * abs(b.days_since_last_fight - 180.0)
    notice = (-0.25 if a.late_replacement else 0.0) + (0.25 if b.late_replacement else 0.0)
    if ctx.short_notice_days is not None and ctx.short_notice_days <= 14:
        notice += -0.08 if a.late_replacement else 0.0
        notice += 0.08 if b.late_replacement else 0.0
    return striking + grappling + physical + history + rest + notice


def project_fight(a: FighterSnapshot, b: FighterSnapshot, ctx: FightContext) -> FightProjection:
    base = _feature_score(a, b, ctx)
    p_a = _safe(_logistic(base), 0.05, 0.95)

    pace = (a.sig_strikes_landed_pm + b.sig_strikes_landed_pm) / 2.0
    finish_pressure = (
        0.65 * ((a.finish_win_rate + b.finish_win_rate) / 2.0)
        + 0.15 * ((a.finish_loss_rate + b.finish_loss_rate) / 2.0)
        + 0.04 * pace
        + 0.025 * (a.submissions_per_15 + b.submissions_per_15)
        + 0.015 * (a.knockdowns_per_15 + b.knockdowns_per_15)
    )
    round_adj = 0.10 if ctx.rounds >= 5 else 0.0
    p_inside = _safe(_logistic(-0.55 + finish_pressure + round_adj), 0.12, 0.88)
    p_gtd = 1.0 - p_inside

    a_finish_share = _safe(
        0.5 + 0.20 * (a.finish_win_rate - b.finish_win_rate)
        + 0.08 * (a.knockdowns_per_15 - b.knockdowns_per_15)
        + 0.06 * (a.submissions_per_15 - b.submissions_per_15),
        0.15,
        0.85,
    )
    p_a_finish = p_inside * a_finish_share
    p_b_finish = p_inside - p_a_finish

    a_sub_share = _safe(0.25 + 0.16 * a.submissions_per_15 + 0.08 * a.takedowns_per_15, 0.08, 0.75)
    b_sub_share = _safe(0.25 + 0.16 * b.submissions_per_15 + 0.08 * b.takedowns_per_15, 0.08, 0.75)

    p_a_sub = p_a_finish * a_sub_share
    p_a_ko = p_a_finish - p_a_sub
    p_b_sub = p_b_finish * b_sub_share
    p_b_ko = p_b_finish - p_b_sub

    p_a_dec = _safe(p_a - p_a_finish, 0.0, 1.0)
    p_b_dec = _safe((1.0 - p_a) - p_b_finish, 0.0, 1.0)

    uncertainty = _safe(
        0.05
        + 0.22 * max(a.missingness, b.missingness)
        + (0.08 if a.late_replacement or b.late_replacement else 0.0)
        + (0.04 if min(a.wins + a.losses, b.wins + b.losses) < 5 else 0.0),
        0.05,
        0.35,
    )
    return FightProjection(
        fighter_a=a.name,
        fighter_b=b.name,
        p_a_win=p_a,
        p_b_win=1.0 - p_a,
        p_goes_distance=p_gtd,
        p_inside_distance=p_inside,
        p_a_ko=p_a_ko,
        p_a_sub=p_a_sub,
        p_a_dec=p_a_dec,
        p_b_ko=p_b_ko,
        p_b_sub=p_b_sub,
        p_b_dec=p_b_dec,
        uncertainty=uncertainty,
    )


def american_to_implied(odds: int) -> float:
    try:
        return 1.0 / american_to_decimal(odds)
    except TruthGateError as exc:
        raise ValueError(f"UFC_ODDS_INVALID:{exc}") from exc


def no_vig_two_way(odds_a: int, odds_b: int) -> tuple[float, float]:
    pa = american_to_implied(odds_a)
    pb = american_to_implied(odds_b)
    s = pa + pb
    if not isfinite(s) or s <= 0.0:
        raise ValueError("UFC_DEVIG_INVALID")
    return pa / s, pb / s


def expected_value(prob: float, american_odds: int) -> float:
    p = _probability(prob, "prob")
    dec = american_to_decimal(american_odds)
    value = p * (dec - 1.0) - (1.0 - p)
    return 0.0 if abs(value) < 1e-12 else value


def fair_american(prob: float) -> int:
    p = _probability(prob, "prob", open_interval=True)
    if p >= 0.5:
        return round(-100.0 * p / (1.0 - p))
    return round(100.0 * (1.0 - p) / p)


def monte_carlo(proj: FightProjection, n: int = 250_000, seed: int = 330) -> Dict[str, float]:
    if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
        raise ValueError("UFC_MONTE_CARLO_N_POSITIVE_INTEGER_REQUIRED")
    rng = Random(seed)
    counts = {"a_win": 0, "b_win": 0, "gtd": 0, "a_ko": 0, "a_sub": 0, "a_dec": 0, "b_ko": 0, "b_sub": 0, "b_dec": 0}
    probs = [
        ("a_ko", proj.p_a_ko), ("a_sub", proj.p_a_sub), ("a_dec", proj.p_a_dec),
        ("b_ko", proj.p_b_ko), ("b_sub", proj.p_b_sub), ("b_dec", proj.p_b_dec),
    ]
    total = sum(p for _, p in probs)
    if not isfinite(total) or total <= 0.0:
        raise ValueError("UFC_PROJECTION_PROBABILITY_MASS_INVALID")
    probs = [(k, p / total) for k, p in probs]
    for _ in range(n):
        u = rng.random()
        c = 0.0
        outcome = probs[-1][0]
        for key, p in probs:
            c += p
            if u <= c:
                outcome = key
                break
        counts[outcome] += 1
        if outcome.startswith("a_"):
            counts["a_win"] += 1
        else:
            counts["b_win"] += 1
        if outcome.endswith("dec"):
            counts["gtd"] += 1
    return {k: v / n for k, v in counts.items()}


def truth_gate(*, prob: float, odds: int, market_novig: float, uncertainty: float,
               min_edge: float = 0.025, min_ev: float = 0.03, max_uncertainty: float = 0.20) -> Mapping[str, object]:
    p = _probability(prob, "prob")
    market_p = _probability(market_novig, "market_novig")
    u = _probability(uncertainty, "uncertainty")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(float(v)) or float(v) < 0.0 for v in (min_edge, min_ev, max_uncertainty)):
        raise ValueError("UFC_TRUTH_GATE_THRESHOLDS_INVALID")
    edge = p - market_p
    ev = expected_value(p, odds)
    passed = edge >= float(min_edge) and ev >= float(min_ev) and u <= float(max_uncertainty)
    return {"pass": passed, "edge": edge, "ev": ev, "uncertainty": u,
            "fair_odds": fair_american(p)}
