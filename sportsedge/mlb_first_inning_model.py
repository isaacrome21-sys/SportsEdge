"""Pure-math first-inning pricing from verified team history pools.

Inputs are integer count pools built ONLY from verified StatsAPI linescores
(see mlb_first_inning_data). No league priors, no market prices, no
caller-supplied features. Research only.

Method: each half-inning rate is a Jeffreys-smoothed Poisson mean
((sum + 0.5) / n -- non-informative Gamma(1/2, 0) posterior, NOT a league
prior), blended 50/50 between the batting team's own rate and the opponent's
allow rate. Halves are treated as independent, matching the validated
held-out recipe of the existing first-inning engine.

Fail-closed: every pool must clear MIN_HISTORY_GAMES; probabilities are
strictly interior (0, 1) so the harness log-loss never sees degeneracy.
"""
from __future__ import annotations

from math import exp, factorial, isfinite

FIRST_INNING_MODEL_VERSION = "mlb_first_inning_team_rates_poisson_jeffreys_v1"
MIN_HISTORY_GAMES = 10
MAX_HISTORY_GAMES = 30
PROB_FLOOR = 1e-6

# Markets the model can price from verified linescore pools.
MODEL_MARKETS = frozenset({
    "FIRST_INNING_RUNS",        # game 1st-inning runs (NRFI/YRFI at 0.5)
    "FIRST_INNING_TEAM_RUNS",   # one team's 1st-inning runs
    "FIRST_INNING_HITS",        # one team's 1st-inning hits
    "TEAM_HITS",                # one team's full-game hits
})

# Markets with no free verified data path: explicit block reasons.
BLOCKED_MARKETS = {
    "FIRST_INNING_HR": "FIRST_INNING_HR_NOT_IN_VERIFIED_LINESCORE",
    "FIRST_INNING_PITCHES": "FIRST_INNING_PITCHES_NO_VERIFIED_PER_INNING_HISTORY",
}


class FirstInningModelError(ValueError):
    pass


def _pool(values, name):
    if not isinstance(values, (list, tuple)):
        raise FirstInningModelError(name + "_POOL_NOT_SEQUENCE")
    if len(values) > MAX_HISTORY_GAMES:
        raise FirstInningModelError(name + "_POOL_EXCEEDS_MAX_HISTORY")
    if len(values) < MIN_HISTORY_GAMES:
        raise FirstInningModelError(
            "FIRST_INNING_HISTORY_INSUFFICIENT:" + name)
    out = []
    for v in values:
        if isinstance(v, bool):
            raise FirstInningModelError(name + "_POOL_VALUE_INVALID")
        try:
            n = int(v)
        except (ValueError, TypeError, OverflowError) as exc:
            raise FirstInningModelError(name + "_POOL_VALUE_INVALID") from exc
        if n < 0 or float(v) != n:
            raise FirstInningModelError(name + "_POOL_VALUE_INVALID")
        out.append(n)
    return out


def jeffreys_mean(values):
    """Non-informative smoothed rate: (sum + 0.5) / n. No league data."""
    total = sum(values)
    n = len(values)
    if n <= 0:
        raise FirstInningModelError("JEFFREYS_MEAN_EMPTY_POOL")
    return (total + 0.5) / n


def blended_rate(offense_pool, opponent_allow_pool):
    """50/50 blend of own rate and opponent allow rate (validated recipe)."""
    return 0.5 * (jeffreys_mean(offense_pool) + jeffreys_mean(opponent_allow_pool))


def _interior(p):
    if not isfinite(p):
        raise FirstInningModelError("FIRST_INNING_PROBABILITY_NONFINITE")
    return min(1.0 - PROB_FLOOR, max(PROB_FLOOR, p))


def poisson_over(line, lam):
    """P(X > line) for Poisson(lam); line must be a non-negative half-integer
    or integer (lines like 0.5, 6.5)."""
    if not isfinite(lam) or lam <= 0:
        raise FirstInningModelError("FIRST_INNING_LAMBDA_INVALID")
    if not isfinite(line) or line < 0:
        raise FirstInningModelError("FIRST_INNING_LINE_INVALID")
    if abs(line - round(line)) not in (0.0, 0.5):
        raise FirstInningModelError("FIRST_INNING_LINE_UNSUPPORTED")
    k = int(line // 1)  # P(X > line) = P(X >= k+1) for half-integer lines
    cdf = 0.0
    term = exp(-lam)
    for i in range(0, k + 1):
        if i == 0:
            term = exp(-lam)
        else:
            term *= lam / i
        cdf += term
    return _interior(1.0 - cdf)


def price_game_first_inning_runs(*, away_for, home_against, home_for,
                                 away_against, line=0.5):
    """Game first-inning runs over/under. line 0.5: OVER=YRFI, UNDER=NRFI."""
    if abs(float(line) - 0.5) > 1e-9:
        raise FirstInningModelError("FIRST_INNING_RUNS_LINE_MUST_BE_0_5")
    lam_away = blended_rate(_pool(away_for, "away_for"),
                            _pool(home_against, "home_against"))
    lam_home = blended_rate(_pool(home_for, "home_for"),
                            _pool(away_against, "away_against"))
    p_over = _interior(1.0 - exp(-(lam_away + lam_home)))
    return {"p_over": p_over, "p_under": _interior(1.0 - p_over),
            "lambda_away": lam_away, "lambda_home": lam_home}


MIN_STARTER_STARTS = 5


def price_game_first_inning_runs_with_starter(
        *, away_for, home_starter_allowed, home_for, away_starter_allowed,
        line=0.5):
    """Game first-inning runs with verified starter splits.

    Each half blends the batting team's own 1st-inning scoring rate with the
    opposing STARTING PITCHER's verified 1st-inning runs-allowed rate
    (gameLog starts x linescore). Team defense rates are superseded by the
    actual starter -- strictly more specific, still fully verified.
    """
    if abs(float(line) - 0.5) > 1e-9:
        raise FirstInningModelError("FIRST_INNING_RUNS_LINE_MUST_BE_0_5")
    lam_away = blended_rate(
        _pool(away_for, "away_for"),
        _starter_pool(home_starter_allowed, "home_starter_allowed"))
    lam_home = blended_rate(
        _pool(home_for, "home_for"),
        _starter_pool(away_starter_allowed, "away_starter_allowed"))
    p_over = _interior(1.0 - exp(-(lam_away + lam_home)))
    return {"p_over": p_over, "p_under": _interior(1.0 - p_over),
            "lambda_away": lam_away, "lambda_home": lam_home}


def _starter_pool(values, name):
    if not isinstance(values, (list, tuple)):
        raise FirstInningModelError(name + "_POOL_NOT_SEQUENCE")
    if len(values) < MIN_STARTER_STARTS:
        raise FirstInningModelError(
            "STARTER_FIRST_INNING_HISTORY_INSUFFICIENT:" + name)
    out = []
    for v in values:
        if isinstance(v, bool):
            raise FirstInningModelError(name + "_POOL_VALUE_INVALID")
        try:
            n = int(v)
        except (ValueError, TypeError, OverflowError) as exc:
            raise FirstInningModelError(name + "_POOL_VALUE_INVALID") from exc
        if n < 0 or float(v) != n:
            raise FirstInningModelError(name + "_POOL_VALUE_INVALID")
        out.append(n)
    return out


def _binary_pool(values, name, minimum):
    checked = _starter_pool(values, name) if minimum == MIN_STARTER_STARTS \
        else _pool(values, name)
    for v in checked:
        if v not in (0, 1):
            raise FirstInningModelError(name + "_NOT_BINARY_INDICATOR")
    return checked


def jeffreys_binary_rate(indicators):
    """Jeffreys Beta(1/2, 1/2) posterior mean of a binary rate.

    Non-informative; uses no league data."""
    n = len(indicators)
    if n <= 0:
        raise FirstInningModelError("JEFFREYS_BINARY_EMPTY_POOL")
    return (sum(indicators) + 0.5) / (n + 1.0)


FIRST_INNING_BINARY_VERSION = "mlb_first_inning_binary_starter_jeffreys_v1"


def price_first_inning_binary(*, away_score_ind, home_starter_allow_ind,
                              home_score_ind, away_starter_allow_ind):
    """P(YRFI/NRFI) from Jeffreys-smoothed binary 1st-inning indicators.

    Each half-inning: p(score) = 1/2 J(team scored in 1st over prior games)
      + 1/2 J(opposing starter allowed a 1st-inning run over prior starts).
    P(YRFI) = 1 - (1 - p_away)(1 - p_home). Halves independent.
    Binary indicators avoid the Poisson link, which is badly misspecified
    for 1st-inning runs (overdispersed: P(YRFI) << 1 - exp(-mean)).
    No league priors, no market data. Strictly interior probabilities.
    """
    p_away = 0.5 * (
        jeffreys_binary_rate(_binary_pool(away_score_ind, "away_score_ind",
                                          MIN_HISTORY_GAMES))
        + jeffreys_binary_rate(_binary_pool(home_starter_allow_ind,
                                            "home_starter_allow_ind",
                                            MIN_STARTER_STARTS)))
    p_home = 0.5 * (
        jeffreys_binary_rate(_binary_pool(home_score_ind, "home_score_ind",
                                          MIN_HISTORY_GAMES))
        + jeffreys_binary_rate(_binary_pool(away_starter_allow_ind,
                                            "away_starter_allow_ind",
                                            MIN_STARTER_STARTS)))
    p_yrfi = _interior(1.0 - (1.0 - p_away) * (1.0 - p_home))
    return {"p_over": p_yrfi, "p_under": _interior(1.0 - p_yrfi),
            "p_away_scores": p_away, "p_home_scores": p_home,
            "model_version": FIRST_INNING_BINARY_VERSION}


def price_team_first_inning(market, *, team_for, team_against, line=0.5):
    """FIRST_INNING_TEAM_RUNS / FIRST_INNING_HITS over/under for one team."""
    if market not in ("FIRST_INNING_TEAM_RUNS", "FIRST_INNING_HITS"):
        raise FirstInningModelError("FIRST_INNING_TEAM_MARKET_UNSUPPORTED:" + str(market))
    if abs(float(line) - 0.5) > 1e-9:
        raise FirstInningModelError(market + "_LINE_MUST_BE_0_5")
    lam = blended_rate(_pool(team_for, "team_for"),
                       _pool(team_against, "team_against"))
    p_over = poisson_over(line, lam)
    return {"p_over": p_over, "p_under": _interior(1.0 - p_over),
            "lambda": lam}


def price_team_hits(*, team_for, team_against, line):
    """TEAM_HITS over/under for one team's full-game hits."""
    try:
        ln = float(line)
    except (ValueError, TypeError) as exc:
        raise FirstInningModelError("TEAM_HITS_LINE_INVALID") from exc
    if not isfinite(ln) or ln < 0 or ln > 30:
        raise FirstInningModelError("TEAM_HITS_LINE_INVALID")
    if abs(ln - round(ln)) not in (0.0, 0.5):
        raise FirstInningModelError("TEAM_HITS_LINE_UNSUPPORTED")
    lam = blended_rate(_pool(team_for, "team_for"),
                       _pool(team_against, "team_against"))
    p_over = poisson_over(ln, lam)
    return {"p_over": p_over, "p_under": _interior(1.0 - p_over),
            "lambda": lam}
