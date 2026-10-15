"""Chronological, unsealed research benchmark for MLB period run totals.

Compares strictly-prior empirical CDF to a strictly-prior Poisson baseline.
No market quotes, sealed holdouts, deployment or betting authority.
"""
from __future__ import annotations

from math import exp, lgamma, log

from sportsedge.mlb_period_counts_empirical import (
    _instant, period_run_distribution,
)


def _poisson_pmf(k: int, mean: float) -> float:
    if mean < 0:
        raise ValueError("NEGATIVE_MEAN")
    if mean == 0:
        return float(k == 0)
    return exp(-mean + k * log(mean) - lgamma(k + 1))


def _prob_over_half_line(pmf: dict, line: float) -> float:
    return sum(float(p) for k, p in pmf.items() if int(k) > line)


def evaluate_period_walkforward(
    games, *, innings: int, min_train: int = 20, half_line: float = 1.5,
) -> dict:
    """Score chronological forward predictions against observed period totals.

    Input rows require unique game IDs, timezone-aware start times, and
    nine completed inning counts and independently evidenced result_available_at.
    Same-timestamp games cannot train on one another. Result availability
    must strictly precede target start. Brier score is lower-is-better.
    """
    if not isinstance(half_line, (float, int)) or isinstance(half_line, bool) or half_line < 0 or float(half_line) % 1 != .5:
        raise ValueError("HALF_INTEGER_LINE_REQUIRED")
    ordered = sorted(games, key=lambda g: _instant(g["start_time"]))
    seen = set()
    for g in ordered:
        gid = g.get("game_id")
        if not isinstance(gid, (str, int)) or isinstance(gid, bool) or not str(gid) or str(gid) in seen:
            raise ValueError("INVALID_OR_DUPLICATE_GAME_ID")
        seen.add(str(gid))
    # Fail closed before scoring any target. A prior start does not prove
    # its result was known at the target cutoff.
    for g in ordered:
        if "result_available_at" not in g:
            raise ValueError("MISSING_RESULT_AVAILABILITY")
        available = _instant(g["result_available_at"])
        if available <= _instant(g["start_time"]):
            raise ValueError("RESULT_AVAILABLE_BEFORE_START")
    # Never score a target against a training pool that includes a result
    # whose declared availability is after the target cutoff.
    scores = []
    for row in ordered:
        cutoff = _instant(row["start_time"])
        prior = [g for g in ordered if _instant(g["start_time"]) < cutoff
                 and _instant(g["result_available_at"]) < cutoff]
        if len(prior) < min_train:
            continue
        empirical = period_run_distribution(prior, cutoff=row["start_time"],
                                            innings=innings, min_games=min_train)
        # Validate observed target without altering its event timestamp.
        inning_runs = row.get("inning_runs")
        if (not isinstance(inning_runs, (list, tuple)) or len(inning_runs) < 9
                or any(not isinstance(x, int) or isinstance(x, bool) or x < 0
                       for x in inning_runs)):
            raise ValueError("INVALID_TARGET_INNINGS")
        observed = int(sum(inning_runs[:innings]) > half_line)
        p_emp = _prob_over_half_line(empirical["pmf"], half_line)
        mu = empirical["sample_mean"]
        # Tail by complement avoids truncation of high-scoring outcomes.
        threshold = int(half_line)
        p_base = max(0., min(1., 1 - sum(_poisson_pmf(k, mu) for k in range(threshold + 1))))
        scores.append((p_emp - observed, p_base - observed))
    if not scores:
        raise ValueError("NO_FORWARD_EVALUATION_ROWS")
    n = len(scores)
    emp_brier = sum(e * e for e, _ in scores) / n
    baseline_brier = sum(b * b for _, b in scores) / n
    return {
        "schema": "MLB_PERIOD_WALKFORWARD_RESEARCH_V1",
        "period": f"FIRST_{innings}",
        "forward_predictions": n,
        "empirical_brier": emp_brier,
        "poisson_baseline_brier": baseline_brier,
        "empirical_minus_baseline_brier": emp_brier - baseline_brier,
        "better_than_baseline": emp_brier < baseline_brier,
        "unsealed_research_only": True,
        "validated": False,
        "play_authorized": False,
    }
