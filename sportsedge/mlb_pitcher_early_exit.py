"""Research-only early-exit re-tailing for pitcher strikeout distributions.

Standalone research module implementing the frozen construction in
docs/MLB_PITCHER_EARLY_EXIT_PREREG_V1.md. It is NOT imported by any runner,
card path, or the frozen forward protocol, and it changes no existing
engine tail. It answers one narrow question: what does a pitcher's K
distribution look like if the league's empirical starter-exit structure
(hook / leash / normal states) is mixed in, instead of reading K totals
straight off the pitcher's own prior starts?

Construction (frozen in the preregistration):
  * Historical starts (completed seasons) are assigned one state, in
    order: HOOK if runs allowed >= 5, else LEASH if pitches <= 65, else
    NORMAL.
  * Per state: empirical distribution of total outs recorded.
  * For a target pitcher with own K rate lambda (K per out, from his own
    strictly-prior starts), the component distribution is
        P(K = k) = sum_s w_s * sum_o P_s(O = o) * Poisson(k; lambda * o)
    with scenario weights w_s equal to the historical state frequencies.

Also provides the preregistered reconstruction of the EXISTING engine's
implied pmf (survival-differencing of the Jeffreys-smoothed empirical
tails in sportsedge/pitcher_joint_engine.py) so the two can be scored on
the same realized outcomes. Deterministic; no randomness anywhere.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

COMPONENT_VERSION = "mlb_pitcher_early_exit_v1"
STATUS = "RESEARCH_ONLY_NOT_WIRED_NO_PRICING_IMPACT"

HOOK_RUNS_MIN = 5
LEASH_PITCHES_MAX = 65
STATES = ("HOOK", "LEASH", "NORMAL")
MAX_OUTS = 27
K_SUPPORT_MAX = 80


def outs_from_ip(ip: Any) -> int:
    """MLB inningsPitched notation -> total outs. '4.1' means 4 1/3 = 13."""
    s = str(ip).strip()
    if "." in s:
        whole, part = s.split(".", 1)
        part_i = int(part)
        if part_i not in (0, 1, 2):
            raise ValueError(f"inningsPitched partial must be 0, 1 or 2: {ip!r}")
        return 3 * int(whole) + part_i
    return 3 * int(s)


def assign_state(runs_allowed: int, pitches: int | None) -> str:
    """Frozen scenario assignment, in declared order."""
    if runs_allowed >= HOOK_RUNS_MIN:
        return "HOOK"
    if pitches is not None and pitches <= LEASH_PITCHES_MAX:
        return "LEASH"
    return "NORMAL"


def completed_innings(outs: int) -> int:
    return outs // 3


def build_exit_model(starts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate historical starts into the frozen exit model.

    Each start mapping needs: outs (int), runs (int), pitches (int|None),
    strikeouts (int). Returns state weights, per-state outs distributions,
    per-state completed-innings distributions, league K rate, and counts.
    """
    counts = {s: 0 for s in STATES}
    outs_hist = {s: [0] * (MAX_OUTS + 1) for s in STATES}
    total_k = 0
    total_outs = 0
    missing_pitches = 0
    for st in starts:
        o = int(st["outs"])
        if not 0 <= o <= MAX_OUTS:
            raise ValueError(f"starter outs outside [0, {MAX_OUTS}]: {o}")
        p = st.get("pitches")
        if p is None:
            missing_pitches += 1
        state = assign_state(int(st["runs"]), p)
        counts[state] += 1
        outs_hist[state][o] += 1
        total_k += int(st["strikeouts"])
        total_outs += o
    n = sum(counts.values())
    if n == 0:
        raise ValueError("no historical starts supplied")
    weights: dict[str, float] = {}
    outs_dist: dict[str, list[float]] = {}
    band_dist: dict[str, list[float]] = {}
    for s in STATES:
        weights[s] = counts[s] / n
        if counts[s]:
            outs_dist[s] = [c / counts[s] for c in outs_hist[s]]
        else:
            outs_dist[s] = [0.0] * (MAX_OUTS + 1)
        bands = [0.0] * 10
        for o, pr in enumerate(outs_dist[s]):
            bands[completed_innings(o)] += pr
        band_dist[s] = bands
    mix_outs = [sum(weights[s] * outs_dist[s][o] for s in STATES)
                for o in range(MAX_OUTS + 1)]
    mix_bands = [sum(weights[s] * band_dist[s][c] for s in STATES)
                 for c in range(10)]
    pooled_bands = [0.0] * 10
    for st in starts:
        pooled_bands[completed_innings(int(st["outs"]))] += 1.0 / n
    return {
        "n_starts": n,
        "state_counts": counts,
        "missing_pitches": missing_pitches,
        "weights": weights,
        "outs_dist": outs_dist,
        "band_dist": band_dist,
        "mixture_outs_dist": mix_outs,
        "mixture_band_dist": mix_bands,
        "pooled_band_dist": pooled_bands,
        "lambda_league": (total_k / total_outs) if total_outs else 0.0,
        "total_k": total_k,
        "total_outs": total_outs,
    }


def _poisson_pmf(k: int, mu: float) -> float:
    if mu <= 0.0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-mu + k * math.log(mu) - math.lgamma(k + 1))


def component_k_distribution(exit_model: Mapping[str, Any],
                             lam: float) -> list[float]:
    """P_comp(K = k) for k = 0..K_SUPPORT_MAX under the frozen mixture."""
    if lam < 0:
        raise ValueError("lambda must be non-negative")
    mix_outs = exit_model["mixture_outs_dist"]
    pmf = []
    for k in range(K_SUPPORT_MAX + 1):
        total = 0.0
        for o, po in enumerate(mix_outs):
            if po:
                total += po * _poisson_pmf(k, lam * o)
        pmf.append(total)
    return pmf


def component_exit_band_mass(exit_model: Mapping[str, Any], band: int) -> float:
    return float(exit_model["mixture_band_dist"][band])


def existing_engine_pmf(pool_k_counts: Mapping[int, int], n: int) -> list[float]:
    """The existing engine's implied pmf, per preregistration section 3.

    q(k) = count_k / (n + 1) for 1 <= k <= Kmax; the two Jeffreys
    half-masses sit at the feasible boundary atoms 0 and Kmax + 1.
    """
    if n <= 0:
        raise ValueError("pool size must be positive")
    kmax = max(pool_k_counts) if pool_k_counts else 0
    pmf = [0.0] * (kmax + 2)
    for k, c in pool_k_counts.items():
        if k == 0:
            pmf[0] += c / (n + 1)
        else:
            pmf[k] += c / (n + 1)
    pmf[0] += 0.5 / (n + 1)
    pmf[kmax + 1] += 0.5 / (n + 1)
    return pmf


def existing_engine_p_over(pool_values: Sequence[int], line: float,
                           n: int | None = None) -> float:
    """The v4 engine's quoted p_over for PITCHER_K (Jeffreys posterior)."""
    if n is None:
        n = len(pool_values)
    over = sum(1 for v in pool_values if v > line)
    return (0.5 + over) / (n + 1)


def log_score(pmf: Sequence[float], realized: int) -> float:
    """ln P(realized); -inf when the distribution assigns zero mass."""
    if realized < 0 or realized >= len(pmf) or pmf[realized] <= 0.0:
        return float("-inf")
    return math.log(pmf[realized])


def crps(pmf: Sequence[float], realized: int) -> float:
    """CRPS of a discrete distribution on {0..m} against an integer outcome."""
    cdf = 0.0
    total = 0.0
    for k in range(len(pmf) + 2):
        if k < len(pmf):
            cdf += pmf[k]
        total += (cdf - (1.0 if k >= realized else 0.0)) ** 2
        if k >= realized and cdf >= 1.0 - 1e-15:
            break
    return total
