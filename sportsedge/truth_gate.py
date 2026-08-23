from dataclasses import dataclass
import math


class TruthGateError(ValueError):
    pass


@dataclass(frozen=True)
class BetDecision:
    model_status: str
    bet_status: str
    implied_probability: float
    edge: float
    ev_per_dollar: float
    kelly_fraction: float
    push_probability: float = 0.0
    conditional_model_probability: float | None = None


def american_to_decimal(odds: float) -> float:
    if not isinstance(odds, (int, float)) or isinstance(odds, bool) or not math.isfinite(float(odds)):
        raise TruthGateError("american odds must be finite numeric")
    odds = float(odds)
    if -100 < odds < 100:
        raise TruthGateError("valid American odds must be <= -100 or >= +100")
    if abs(odds) > 1_000_000:
        raise TruthGateError("american odds magnitude is implausible")
    return 1.0 + (100.0 / abs(odds) if odds < 0 else odds / 100.0)


def decide_bet(
    model_p: float,
    american_odds: float,
    *,
    fair_market_probability: float,
    bound: bool,
    fresh: bool,
    deployed: bool,
    edge_floor: float,
    kelly_multiplier: float = 0.25,
    push_probability: float = 0.0,
) -> BetDecision:
    if any(type(v) is not bool for v in (bound, fresh, deployed)):
        raise TruthGateError("bound/fresh/deployed must be bool")
    if not isinstance(model_p, (int, float)) or isinstance(model_p, bool) or not math.isfinite(float(model_p)) or not 0 <= float(model_p) <= 1:
        raise TruthGateError("Model_P must be finite in [0,1]")
    if not isinstance(push_probability, (int, float)) or isinstance(push_probability, bool) or not math.isfinite(float(push_probability)) or not 0 <= float(push_probability) < 1:
        raise TruthGateError("push_probability must be finite in [0,1)")
    if float(model_p) + float(push_probability) > 1.0 + 1e-12:
        raise TruthGateError("Model_P + push_probability must be <= 1")
    if not isinstance(fair_market_probability, (int, float)) or isinstance(fair_market_probability, bool) or not math.isfinite(float(fair_market_probability)) or not 0 < float(fair_market_probability) < 1:
        raise TruthGateError("fair_market_probability must be finite in (0,1)")
    if not isinstance(edge_floor, (int, float)) or isinstance(edge_floor, bool) or not math.isfinite(float(edge_floor)) or float(edge_floor) <= 0:
        raise TruthGateError("edge_floor must be finite and > 0")
    if not isinstance(kelly_multiplier, (int, float)) or not math.isfinite(float(kelly_multiplier)) or kelly_multiplier < 0:
        raise TruthGateError("kelly_multiplier must be finite and >= 0")

    dec = american_to_decimal(american_odds)
    fair_market = float(fair_market_probability)
    p_win = float(model_p)
    p_push = float(push_probability)
    p_loss = max(0.0, 1.0 - p_win - p_push)
    non_push = 1.0 - p_push
    conditional_win = p_win / non_push
    conditional_loss = p_loss / non_push

    # Sportsbook paired prices describe the two settled win/loss sides conditional
    # on a non-push result. Edge is therefore compared on that same conditional
    # sample space. EV remains unconditional because pushes return stake.
    edge = conditional_win - fair_market
    ev = p_win * (dec - 1.0) - p_loss
    b = dec - 1.0
    raw_kelly = max(0.0, (b * conditional_win - conditional_loss) / b) if b > 0 else 0.0
    kelly = raw_kelly * float(kelly_multiplier)

    if not (bound and fresh and deployed):
        status = "BLOCKED"
    elif edge <= float(edge_floor) or ev <= 0:
        status = "PASS"
    else:
        status = "OFFICIAL_BET"
    return BetDecision(
        "MODEL_OK",
        status,
        fair_market,
        edge,
        ev,
        kelly,
        p_push,
        conditional_win,
    )
