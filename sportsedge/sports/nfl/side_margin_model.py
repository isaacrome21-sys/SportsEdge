"""NFL side pricing: de-compressed margin mean + key-number margin distribution.

Lane 1 fix for #2384 (side probabilities compressed toward even).

Root cause: ``artifacts/free_models.py`` turned each team's recent average
margin into a rating with a fixed 0.12 multiplier capped at +/-3 points, so a
team that won its last five games by 10 moved the projected margin by only
~1.2 points and every side priced near 50/50 (all-underdog "edges").

This module replaces that with:

1. ``margin_rating_diff`` -- projected home-minus-away margin contribution
   ``b * n/(n+k) * avg_margin`` per team (n = games in the sample, at most
   five, matching ``PublicContext.schedule``). ``b`` and ``k`` were fit by
   least squares on NFL regular seasons 2006-2020 ONLY (nflverse games.csv,
   saved locally) and frozen before the 2021-2025 holdout was scored; see
   ``scripts/backtest_nfl_sides_lane1.py`` and the receipt in
   ``artifacts/nfl_sides_lane1_backtest.json``.
2. ``margin_distribution`` -- a discrete integer-margin distribution: a
   discretized normal around the mean, reweighted by empirical key-number
   weights (3, 7, 10, 6, 14, ... are far more common than a normal says;
   0 is far rarer). Weights fit on 2006-2020 only.
3. ``price_side`` -- push-aware (p_win, p_push, p_loss) for moneyline and
   spreads, including integer lines (3, 7) where the push mass comes from the
   key-number distribution instead of a +/-0.5 normal slice. NFL moneyline
   ties are returned as a push (DK voids/refunds NFL moneyline ties).

Research only. Not validated against closing lines for wagering; nothing here
grants staking or pick authority. The holdout receipt is the only evidence.
"""
from __future__ import annotations

from math import erf, isfinite, sqrt

# --- Frozen parameters (fit on NFL REG 2006-2020 only; holdout 2021-2025) ---
RATING_B = 1.2
RATING_K = 8.0
MARGIN_SD = 14.12
MAX_ABS_MARGIN = 60
# Empirical / discretized-normal frequency ratio for |margin| = j, fit on
# 2006-2020 REG (fit wherever the normal expects >= 30 training games).
# Missing j -> 1.0.
KEY_WEIGHTS: dict[int, float] = {
    0: 0.0976, 1: 0.7335, 2: 0.7434, 3: 2.7731, 4: 0.9659, 5: 0.6863,
    6: 1.2376, 7: 1.9602, 8: 0.8221, 9: 0.351, 10: 1.3062, 11: 0.5822,
    12: 0.3839, 13: 0.6909, 14: 1.5058, 15: 0.4683, 16: 0.7529, 17: 1.1181,
    18: 0.9169, 19: 0.4597, 20: 1.0152, 21: 1.4923, 22: 0.5333, 23: 0.6216,
    24: 1.5934, 25: 0.7704, 26: 0.6863, 27: 1.1963, 28: 1.8037, 29: 0.8963,
}

MODEL_ID = "NFL_SIDE_MARGIN_KEYNUM_V1"


def _shrunk(avg_margin: float, n: int) -> float:
    if n <= 0:
        return 0.0
    return RATING_B * n / (n + RATING_K) * avg_margin


def margin_rating_diff(home_margins, away_margins) -> float:
    """Home-minus-away projected margin contribution (points), excluding HFA."""
    def avg(xs):
        xs = [float(x) for x in xs]
        for x in xs:
            if not isfinite(x):
                raise ValueError("NFL_SIDE_MARGIN_NONFINITE")
        return (sum(xs) / len(xs), len(xs)) if xs else (0.0, 0)
    ha, hn = avg(home_margins)
    aa, an = avg(away_margins)
    return _shrunk(ha, hn) - _shrunk(aa, an)


def _cdf(x: float, mean: float, sd: float) -> float:
    return (1 + erf((x - mean) / (sd * sqrt(2)))) / 2


def margin_distribution(mean: float, sd: float = MARGIN_SD,
                        weights: dict[int, float] | None = None) -> dict[int, float]:
    """P(home margin == m) for integer m, normalized."""
    if not (isfinite(mean) and isfinite(sd) and sd > 0):
        raise ValueError("NFL_SIDE_DISTRIBUTION_INVALID")
    w = KEY_WEIGHTS if weights is None else weights
    out = {}
    for m in range(-MAX_ABS_MARGIN, MAX_ABS_MARGIN + 1):
        p = _cdf(m + 0.5, mean, sd) - _cdf(m - 0.5, mean, sd)
        out[m] = p * w.get(abs(m), 1.0)
    total = sum(out.values())
    return {m: p / total for m, p in out.items()}


def price_side(market: str, side: str, line, home_margin_mean: float,
               *, sd: float = MARGIN_SD, weights=None) -> tuple[float, float, float]:
    """Return (p_win, p_push, p_loss) for an NFL ML or SPREAD side.

    ``line`` is the handicap on the priced side (e.g. -3 for HOME -3).
    """
    market = str(market).upper()
    side = str(side).upper()
    if side not in {"HOME", "AWAY"}:
        raise ValueError("NFL_SIDE_UNKNOWN")
    if market == "ML":
        handicap = 0.0
    elif market == "SPREAD":
        if line is None:
            raise ValueError("NFL_SPREAD_LINE_MISSING")
        handicap = float(line)
        if not isfinite(handicap) or abs(handicap * 2 - round(handicap * 2)) > 1e-9:
            raise ValueError("NFL_SPREAD_LINE_INVALID")
    else:
        raise ValueError("NFL_SIDE_MARKET_UNSUPPORTED")
    dist = margin_distribution(home_margin_mean, sd, weights)
    win = push = 0.0
    for m, p in dist.items():
        own = m if side == "HOME" else -m
        x = own + handicap
        if x > 1e-9:
            win += p
        elif x > -1e-9:
            push += p
    loss = max(0.0, 1.0 - win - push)
    return win, push, loss
