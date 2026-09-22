"""Path-derived NBA fair probabilities, prices and EV.

All probabilities are measured from coherent model paths. Quotes are comparison
inputs only: sportsbook prices never create model probability.
"""
from dataclasses import dataclass
import math
from typing import Iterable


@dataclass(frozen=True)
class NBAFairPrice:
    win_probability: float
    push_probability: float
    lose_probability: float
    fair_decimal: float


def path_outcome(values: Iterable[float], line: float, *, over: bool = True) -> NBAFairPrice:
    vals=tuple(values)
    if not vals:
        raise ValueError("model paths are required")
    if not math.isfinite(line):
        raise ValueError("line must be finite")
    wins=pushes=0
    for value in vals:
        if not math.isfinite(value):
            raise ValueError("path values must be finite")
        diff=value-line if over else line-value
        wins += diff > 0
        pushes += diff == 0
    n=len(vals); losses=n-wins-pushes
    wp=wins/n; pp=pushes/n; lp=losses/n
    # Conditional fair price on resolved outcomes; pushes return stake.
    resolved=wp+lp
    fair=math.inf if wp == 0 else (resolved/wp if resolved else 1.0)
    return NBAFairPrice(wp,pp,lp,fair)


def moneyline_probability(home_final: Iterable[int], away_final: Iterable[int], *, home: bool=True) -> NBAFairPrice:
    h=tuple(home_final); a=tuple(away_final)
    if not h or len(h) != len(a):
        raise ValueError("paired final-score paths are required")
    margins=tuple(x-y for x,y in zip(h,a))
    # Final NBA paths should not tie; line zero still fails honestly if they do.
    return path_outcome(margins,0.0,over=home)


def expected_value(price: NBAFairPrice, decimal_odds: float) -> float:
    if not math.isfinite(decimal_odds) or decimal_odds <= 1.0:
        raise ValueError("decimal_odds must be finite and > 1")
    return price.win_probability*(decimal_odds-1.0) - price.lose_probability


def decimal_to_american(decimal_odds: float) -> float:
    if not math.isfinite(decimal_odds) or decimal_odds <= 1.0:
        raise ValueError("decimal_odds must be finite and > 1")
    return 100.0*(decimal_odds-1.0) if decimal_odds >= 2.0 else -100.0/(decimal_odds-1.0)
