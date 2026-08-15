"""Advanced UFC modeling primitives for SportsEdge.

This module adds four production-facing layers without allowing sportsbook prices
into the fighter model: enriched fighter features, fight-week context penalties,
market-history/CLV tracking, and separately gated prop probabilities.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp
from statistics import mean
from typing import Iterable, Mapping, Sequence

from .ufc_engine import FighterSnapshot, FightContext, fair_american, expected_value


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return min(hi, max(lo, x))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + exp(-x))


@dataclass(frozen=True)
class RoundStats:
    round_number: int
    seconds: float
    sig_landed: float = 0.0
    sig_attempted: float = 0.0
    sig_absorbed: float = 0.0
    takedowns_landed: float = 0.0
    takedowns_attempted: float = 0.0
    control_seconds: float = 0.0
    knockdowns: float = 0.0
    submission_attempts: float = 0.0


@dataclass(frozen=True)
class AdvancedFighterFeatures:
    pace_r1: float
    pace_r2: float
    pace_r3: float
    control_share: float
    takedown_quality: float
    damage_absorbed_index: float
    knockdowns_per_15: float
    finish_vulnerability: float
    opponent_adjusted_striking: float
    opponent_adjusted_grappling: float


def derive_advanced_features(rounds: Sequence[RoundStats], *,
                             opponent_strengths: Sequence[float] | None = None) -> AdvancedFighterFeatures:
    if not rounds:
        return AdvancedFighterFeatures(0, 0, 0, 0, 0, 0, 0, 0.5, 0, 0)
    by_round: dict[int, list[RoundStats]] = {}
    for r in rounds:
        by_round.setdefault(r.round_number, []).append(r)
    def pace(n: int) -> float:
        xs = by_round.get(n, [])
        if not xs:
            return 0.0
        return mean((x.sig_landed / max(x.seconds, 1.0)) * 60.0 for x in xs)
    total_seconds = sum(max(r.seconds, 0.0) for r in rounds)
    control = sum(r.control_seconds for r in rounds)
    td_att = sum(r.takedowns_attempted for r in rounds)
    td_land = sum(r.takedowns_landed for r in rounds)
    sig_abs = sum(r.sig_absorbed for r in rounds)
    kd = sum(r.knockdowns for r in rounds)
    sub = sum(r.submission_attempts for r in rounds)
    strength = mean(opponent_strengths) if opponent_strengths else 0.5
    scale = 0.75 + 0.5 * _clip(strength)
    striking = (sum(r.sig_landed for r in rounds) / max(total_seconds, 1.0)) * 60.0 * scale
    grappling = ((td_land * 1.5) + control / 60.0 + sub * 2.0) / max(total_seconds / 900.0, 1e-6) * scale
    damage_index = sig_abs / max(total_seconds / 60.0, 1e-6)
    vulnerability = _clip(0.30 + 0.035 * damage_index + 0.16 * (kd / max(total_seconds / 900.0, 1e-6)))
    return AdvancedFighterFeatures(
        pace(1), pace(2), pace(3), _clip(control / max(total_seconds, 1.0)),
        _clip(td_land / max(td_att, 1.0)), damage_index,
        kd / max(total_seconds / 900.0, 1e-6), vulnerability, striking, grappling,
    )


@dataclass(frozen=True)
class FightWeekContext:
    short_notice_days: int | None = None
    missed_weight: bool = False
    catchweight: bool = False
    layoff_days: int | None = None
    travel_timezone_hours: float = 0.0
    altitude_ft: float = 0.0
    five_round_experience: int = 0


def context_uncertainty(ctx: FightWeekContext) -> float:
    penalty = 0.0
    if ctx.short_notice_days is not None and ctx.short_notice_days <= 14:
        penalty += 0.07
    if ctx.missed_weight:
        penalty += 0.06
    if ctx.catchweight:
        penalty += 0.025
    if ctx.layoff_days is not None and ctx.layoff_days >= 540:
        penalty += 0.04
    if abs(ctx.travel_timezone_hours) >= 6:
        penalty += 0.02
    if ctx.altitude_ft >= 4000:
        penalty += 0.02
    return min(0.20, penalty)


@dataclass(frozen=True)
class MarketTick:
    event_id: str
    market: str
    selection: str
    timestamp: str
    price: int
    source: str


def implied_probability(odds: int) -> float:
    return 100.0 / (odds + 100.0) if odds > 0 else (-odds) / ((-odds) + 100.0)


def clv_probability(open_price: int, close_price: int, bet_price: int) -> Mapping[str, float]:
    """Return probability-space line movement and CLV.

    Positive clv means the bettor captured a better implied price than the close.
    """
    p_open = implied_probability(open_price)
    p_close = implied_probability(close_price)
    p_bet = implied_probability(bet_price)
    return {"open_implied": p_open, "close_implied": p_close,
            "bet_implied": p_bet, "market_move": p_close - p_open,
            "clv": p_close - p_bet}


@dataclass(frozen=True)
class PropProjection:
    p_gtd: float
    p_inside_distance: float
    p_ko: float
    p_sub: float
    p_decision: float
    p_over_15: float
    p_over_25: float
    uncertainty: float


def project_props(a: FighterSnapshot, b: FighterSnapshot, ctx: FightContext,
                  *, advanced_a: AdvancedFighterFeatures | None = None,
                  advanced_b: AdvancedFighterFeatures | None = None,
                  fight_week: FightWeekContext | None = None) -> PropProjection:
    """Sportsbook-independent challenger prop model.

    This is intentionally separate from ML. It must be calibrated on prop-specific
    historical targets before promotion to official betting status.
    """
    aa = advanced_a or AdvancedFighterFeatures(0,0,0,0,0,0,0,0.5,0,0)
    bb = advanced_b or AdvancedFighterFeatures(0,0,0,0,0,0,0,0.5,0,0)
    avg_finish = (a.finish_win_rate + b.finish_win_rate + a.finish_loss_rate + b.finish_loss_rate) / 4.0
    pace = (a.sig_strikes_landed_pm + b.sig_strikes_landed_pm + aa.pace_r1 + bb.pace_r1) / 4.0
    danger = (aa.finish_vulnerability + bb.finish_vulnerability) / 2.0
    sub_pressure = (a.submissions_per_15 + b.submissions_per_15) / 2.0
    kd_pressure = (a.knockdowns_per_15 + b.knockdowns_per_15 + aa.knockdowns_per_15 + bb.knockdowns_per_15) / 4.0
    five = 0.18 if ctx.rounds >= 5 else 0.0
    p_inside = _clip(_sigmoid(-1.10 + 1.55*avg_finish + 0.08*pace + 0.45*danger + 0.10*sub_pressure + 0.08*kd_pressure + five), 0.08, 0.92)
    p_gtd = 1.0 - p_inside
    sub_share = _clip(_sigmoid(-1.2 + 0.9*sub_pressure + 0.25*((a.takedowns_per_15+b.takedowns_per_15)/2.0)), 0.08, 0.72)
    p_sub = p_inside * sub_share
    p_ko = p_inside - p_sub
    p_dec = p_gtd
    p_over15 = _clip(p_gtd + 0.55*p_inside, 0.05, 0.97)
    p_over25 = _clip(p_gtd + (0.22 if ctx.rounds >= 5 else 0.0)*p_inside, 0.02, 0.95)
    uncertainty = 0.13 + 0.18*max(a.missingness,b.missingness)
    if fight_week:
        uncertainty += context_uncertainty(fight_week)
    return PropProjection(p_gtd,p_inside,p_ko,p_sub,p_dec,p_over15,p_over25,min(0.35,uncertainty))


def prop_truth_gate(*, prob: float, odds: int, market_no_vig: float,
                    uncertainty: float, calibrated: bool,
                    min_edge: float = 0.04, min_ev: float = 0.05,
                    max_uncertainty: float = 0.18) -> Mapping[str, object]:
    edge = prob - market_no_vig
    ev = expected_value(prob, odds)
    passed = calibrated and edge >= min_edge and ev >= min_ev and uncertainty <= max_uncertainty
    reason = "PASS" if passed else ("PROP_NOT_CALIBRATED" if not calibrated else "PROP_TRUTH_GATE")
    return {"pass": passed, "reason": reason, "edge": edge, "ev": ev,
            "uncertainty": uncertainty, "fair_odds": fair_american(prob)}


@dataclass(frozen=True)
class ValidationSlice:
    name: str
    n: int
    accuracy: float
    brier: float


def validation_slices(rows: Iterable[Mapping[str, object]], *, probability_key: str = "p",
                      outcome_key: str = "y") -> list[ValidationSlice]:
    data = list(rows)
    groups: dict[str, list[Mapping[str, object]]] = {"all": data}
    for r in data:
        p = float(r[probability_key])
        groups.setdefault("favorite" if p >= 0.5 else "underdog", []).append(r)
        wc = str(r.get("weight_class") or "unknown")
        groups.setdefault(f"weight:{wc}", []).append(r)
        year = str(r.get("date") or "")[:4] or "unknown"
        groups.setdefault(f"year:{year}", []).append(r)
    out=[]
    for name, items in groups.items():
        if not items:
            continue
        ps=[float(x[probability_key]) for x in items]; ys=[int(x[outcome_key]) for x in items]
        acc=sum(1 for p,y in zip(ps,ys) if (p>=0.5)==bool(y))/len(items)
        brier=sum((p-y)**2 for p,y in zip(ps,ys))/len(items)
        out.append(ValidationSlice(name,len(items),acc,brier))
    return sorted(out,key=lambda x:x.name)
