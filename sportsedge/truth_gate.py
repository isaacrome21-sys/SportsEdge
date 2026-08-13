from dataclasses import dataclass
import math


class TruthGateError(ValueError):
    pass


DEFAULT_MIN_EDGE = 0.025


@dataclass(frozen=True)
class BetDecision:
    model_status: str
    bet_status: str
    implied_probability: float
    edge: float
    ev_per_dollar: float
    kelly_fraction: float


def american_to_decimal(odds: float) -> float:
    if not isinstance(odds, (int, float)) or isinstance(odds, bool) or not math.isfinite(float(odds)):
        raise TruthGateError("american odds must be finite numeric")
    odds = float(odds)
    if -100 < odds < 100:
        raise TruthGateError("valid American odds must be <= -100 or >= +100")
    if abs(odds) > 1_000_000:
        raise TruthGateError("american odds magnitude is implausible")
    return 1.0 + (100.0 / abs(odds) if odds < 0 else odds / 100.0)


def decide_bet(model_p: float, american_odds: float, *, bound: bool, fresh: bool, deployed: bool, min_edge: float = DEFAULT_MIN_EDGE, kelly_multiplier: float = 0.25) -> BetDecision:
    if any(type(v) is not bool for v in (bound, fresh, deployed)):
        raise TruthGateError("bound/fresh/deployed must be bool")
    if not isinstance(model_p, (int, float)) or isinstance(model_p, bool) or not math.isfinite(float(model_p)) or not 0 <= float(model_p) <= 1:
        raise TruthGateError("Model_P must be finite in [0,1]")
    if not isinstance(min_edge, (int, float)) or not math.isfinite(float(min_edge)) or min_edge < 0:
        raise TruthGateError("min_edge must be finite and >= 0")
    if not isinstance(kelly_multiplier, (int, float)) or not math.isfinite(float(kelly_multiplier)) or kelly_multiplier < 0:
        raise TruthGateError("kelly_multiplier must be finite and >= 0")

    dec = american_to_decimal(american_odds)
    implied = 1.0 / dec
    p = float(model_p)
    edge = p - implied
    ev = p * (dec - 1.0) - (1.0 - p)
    b = dec - 1.0
    raw_kelly = max(0.0, (b * p - (1.0 - p)) / b) if b > 0 else 0.0
    kelly = raw_kelly * float(kelly_multiplier)
    effective_min_edge = max(DEFAULT_MIN_EDGE, float(min_edge))

    if not (bound and fresh and deployed):
        status = "BLOCKED"
    elif edge <= effective_min_edge or ev <= 0:
        status = "PASS"
    else:
        status = "OFFICIAL_BET"
    return BetDecision("MODEL_OK", status, implied, edge, ev, kelly)
