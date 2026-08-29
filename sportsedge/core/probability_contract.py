"""Shared probability-basis contracts for SportsEdge Manual/Hybrid execution.

This module prevents a common silent error: comparing a model probability that is
conditioned on no push with a market probability on a different basis. It also keeps
EV unconditional and exposes a deterministic Monte Carlo precision check.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt


class ProbabilityContractError(ValueError):
    pass


def _p(value: float, field: str) -> float:
    out = float(value)
    if not isfinite(out) or not 0.0 <= out <= 1.0:
        raise ProbabilityContractError(f"{field}:PROBABILITY_RANGE")
    return out


def american_to_decimal(odds: float) -> float:
    value = float(odds)
    if not isfinite(value) or value == 0.0 or -100.0 < value < 100.0:
        raise ProbabilityContractError("AMERICAN_ODDS_INVALID")
    return 1.0 + (100.0 / -value if value < 0 else value / 100.0)


@dataclass(frozen=True)
class PushAwareProbability:
    p_win: float
    p_push: float
    p_loss: float

    def validate(self) -> "PushAwareProbability":
        win = _p(self.p_win, "p_win")
        push = _p(self.p_push, "p_push")
        loss = _p(self.p_loss, "p_loss")
        if abs((win + push + loss) - 1.0) > 1e-9:
            raise ProbabilityContractError("PROBABILITY_MASS_NOT_ONE")
        if push >= 1.0:
            raise ProbabilityContractError("ALL_PUSH_INVALID")
        return self

    @property
    def p_win_nonpush(self) -> float:
        self.validate()
        return self.p_win / (1.0 - self.p_push)


def push_conditioned_edge(model: PushAwareProbability, market_novig_nonpush_p: float) -> float:
    """Compare both model and paired sportsbook market on the same non-push basis."""
    market = _p(market_novig_nonpush_p, "market_novig_nonpush_p")
    return model.p_win_nonpush - market


def ev_per_dollar(model: PushAwareProbability, american_odds: float) -> float:
    """Unconditional $1 EV. Push returns stake and contributes zero profit/loss."""
    model.validate()
    decimal = american_to_decimal(american_odds)
    return model.p_win * (decimal - 1.0) - model.p_loss


def monte_carlo_standard_error(probability: float, paths: int) -> float:
    p = _p(probability, "probability")
    if isinstance(paths, bool) or int(paths) <= 0:
        raise ProbabilityContractError("MC_PATHS_POSITIVE_INT_REQUIRED")
    return sqrt(p * (1.0 - p) / int(paths))


def require_monte_carlo_precision(
    probability: float,
    *,
    paths: int,
    live_edge_floor: float,
    max_se_fraction_of_edge_floor: float = 0.20,
) -> float:
    floor = float(live_edge_floor)
    fraction = float(max_se_fraction_of_edge_floor)
    if not isfinite(floor) or floor <= 0.0:
        raise ProbabilityContractError("EDGE_FLOOR_POSITIVE_REQUIRED")
    if not isfinite(fraction) or not 0.0 < fraction < 1.0:
        raise ProbabilityContractError("MC_SE_FRACTION_INVALID")
    se = monte_carlo_standard_error(probability, paths)
    if se > floor * fraction + 1e-15:
        raise ProbabilityContractError(
            f"MC_PRECISION_INSUFFICIENT:se={se:.8f}:limit={floor * fraction:.8f}:paths={int(paths)}"
        )
    return se
