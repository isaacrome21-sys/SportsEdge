"""Research-only exact joint team-runs distribution for MLB full-game markets.

NOT REGISTERED. NOT WIRED INTO LIVE PRICING. NOT VALIDATED. Every output carries
``research_only=True`` and ``eligible=False``.

Purpose: an analytic (no Monte Carlo) joint PMF over final (away, home) runs from
which MONEYLINE, RUN_LINE, TOTALS and TEAM_TOTALS are all read through the SAME
production settlement readout (``game_distribution_readout.read_game_probability``),
so push mass on integer lines and alternate ladders are consistent by construction.

Modes
-----
``INDEPENDENT_NB``  mirrors the production V8 simulator semantics exactly
    (per-team gamma frailty -> negative binomial regulation runs; ties resolved by
    the same extra-inning loop: home walk-off wins by exactly one run, away wins
    keep both increments, equal increments repeat for up to 30 rounds, then a
    p_home coin-flip adds one run). It exists to give exact pushes/tails for the
    current model and to test MC agreement.
``SHARED_PACE_NB``  adds one mean-one Gamma(shared_r) game-pace multiplier on top of
    the per-team frailty, inducing positive run correlation between teams while
    preserving each team's unconditional mean. This is the 2027 pre-registered
    challenger (docs/MLB_JOINT_TEAM_RUNS_2027_PREREG.md). ``shared_r`` is NOT fitted
    here; callers must pass a frozen value and no default is supplied.

Inputs are post-calibration simulator means (the same values production passes to
``simulate_game_distribution``). The module does not compute team means.
"""
from __future__ import annotations

from math import exp, isfinite, lgamma, log
from typing import Any, Mapping

from sportsedge.game_distribution_readout import read_game_probability
from sportsedge.source_lineage import canonical_json_sha256
from sportsedge.v7_distribution import (
    V8_INDEPENDENT_EXTRA_HALF_INNING_MEAN,
    V8_INDEPENDENT_TEAM_DISPERSION_R,
)

VERSION = "mlb_joint_team_runs_research_v1"
MODE_INDEPENDENT_NB = "INDEPENDENT_NB"
MODE_SHARED_PACE_NB = "SHARED_PACE_NB"
MODES = frozenset({MODE_INDEPENDENT_NB, MODE_SHARED_PACE_NB})
MAX_REGULATION_RUNS = 80
MAX_EXTRA_ROUNDS = 30  # identical to v7_distribution._resolve_extras
_EXTRA_POISSON_CAP = 30
_TAIL_TOLERANCE = 1e-10
_PACE_GRID = 400
MARKETS = ("MONEYLINE", "RUN_LINE", "TOTALS", "TEAM_TOTALS")


class JointTeamRunsError(ValueError):
    pass


def _positive(value: Any, name: str, *, upper: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JointTeamRunsError(f"{name}_NOT_NUMERIC")
    out = float(value)
    if not isfinite(out) or out <= 0:
        raise JointTeamRunsError(f"{name}_NOT_FINITE_POSITIVE")
    if upper is not None and out > upper:
        raise JointTeamRunsError(f"{name}_OUT_OF_RANGE")
    return out


def _nb_pmf(mean: float, r: float, n_max: int) -> list[float]:
    p = r / (r + mean)
    log_p, log_q = log(p), log(1.0 - p)
    base = lgamma(r)
    return [exp(lgamma(k + r) - base - lgamma(k + 1) + r * log_p + k * log_q) for k in range(n_max + 1)]


def _poisson_pmf(lam: float, n_max: int) -> list[float]:
    out = [exp(-lam)]
    for k in range(1, n_max + 1):
        out.append(out[-1] * lam / k)
    return out


def _regulation_joint(away: float, home: float, team_r: float, shared_r: float | None) -> list[list[float]]:
    n = MAX_REGULATION_RUNS
    if shared_r is None:
        pa, ph = _nb_pmf(away, team_r, n), _nb_pmf(home, team_r, n)
        if 1.0 - sum(pa) > _TAIL_TOLERANCE or 1.0 - sum(ph) > _TAIL_TOLERANCE:
            raise JointTeamRunsError("REGULATION_TAIL_EXCEEDS_SUPPORT")
        return [[a * h for h in ph] for a in pa]
    # Integrate the shared mean-one Gamma(shared_r, 1/shared_r) pace on a
    # quantile-free midpoint grid over [0, mean + 10 sd]; weights renormalized.
    sd = (1.0 / shared_r) ** 0.5
    upper = 1.0 + 10.0 * sd
    step = upper / _PACE_GRID
    log_norm = shared_r * log(shared_r) - lgamma(shared_r)
    grid = []
    for i in range(_PACE_GRID):
        x = (i + 0.5) * step
        grid.append((x, exp(log_norm + (shared_r - 1.0) * log(x) - shared_r * x) * step))
    wsum = sum(w for _, w in grid)
    if not 0.999 < wsum < 1.001:
        raise JointTeamRunsError("SHARED_PACE_QUADRATURE_UNSTABLE")
    joint = [[0.0] * (n + 1) for _ in range(n + 1)]
    for x, w in grid:
        w /= wsum
        pa, ph = _nb_pmf(away * x, team_r, n), _nb_pmf(home * x, team_r, n)
        for i, a in enumerate(pa):
            wa = w * a
            if wa == 0.0:
                continue
            row = joint[i]
            for j, h in enumerate(ph):
                row[j] += wa * h
    if 1.0 - sum(map(sum, joint)) > 1e-8:
        raise JointTeamRunsError("REGULATION_TAIL_EXCEEDS_SUPPORT")
    return joint


def _extra_increments(away: float, home: float, extra_mean: float) -> dict[tuple[int, int], float]:
    """Distribution of (away_add, home_add) applied to a regulation tie."""
    avg = max(1e-9, (away + home) / 2.0)
    pa = _poisson_pmf(extra_mean * away / avg, _EXTRA_POISSON_CAP)
    ph = _poisson_pmf(extra_mean * home / avg, _EXTRA_POISSON_CAP)
    out: dict[tuple[int, int], float] = {}
    offsets = {0: 1.0}  # cumulative equal runs added by tied rounds
    for _ in range(MAX_EXTRA_ROUNDS):
        nxt: dict[int, float] = {}
        for off, mass in offsets.items():
            for ax, p_ax in enumerate(pa):
                for hx, p_hx in enumerate(ph):
                    m = mass * p_ax * p_hx
                    if m < 1e-20:
                        continue
                    if hx > ax:
                        key = (off + ax, off + ax + 1)
                    elif ax > hx:
                        key = (off + ax, off + hx)
                    else:
                        nxt[off + ax] = nxt.get(off + ax, 0.0) + m
                        continue
                    out[key] = out.get(key, 0.0) + m
        offsets = {k: v for k, v in nxt.items() if v > 1e-20}
    p_home = home / (home + away)
    for off, mass in offsets.items():
        out[(off, off + 1)] = out.get((off, off + 1), 0.0) + mass * p_home
        out[(off + 1, off)] = out.get((off + 1, off), 0.0) + mass * (1.0 - p_home)
    return out


def build_joint_team_runs(
    *,
    away_mean_runs: Any,
    home_mean_runs: Any,
    mode: str = MODE_INDEPENDENT_NB,
    team_dispersion_r: Any = V8_INDEPENDENT_TEAM_DISPERSION_R,
    shared_pace_r: Any = None,
    extra_half_inning_mean: Any = V8_INDEPENDENT_EXTRA_HALF_INNING_MEAN,
) -> dict[str, Any]:
    if mode not in MODES:
        raise JointTeamRunsError("MODE_UNSUPPORTED")
    away = _positive(away_mean_runs, "AWAY_MEAN_RUNS", upper=15.0)
    home = _positive(home_mean_runs, "HOME_MEAN_RUNS", upper=15.0)
    team_r = _positive(team_dispersion_r, "TEAM_DISPERSION_R", upper=1e6)
    extra = _positive(extra_half_inning_mean, "EXTRA_HALF_INNING_MEAN", upper=5.0)
    shared_r: float | None = None
    if mode == MODE_SHARED_PACE_NB:
        if shared_pace_r is None:
            raise JointTeamRunsError("SHARED_PACE_R_REQUIRED_FROZEN_VALUE")
        shared_r = _positive(shared_pace_r, "SHARED_PACE_R", upper=1e6)
    elif shared_pace_r is not None:
        raise JointTeamRunsError("SHARED_PACE_R_ONLY_FOR_SHARED_MODE")

    reg = _regulation_joint(away, home, team_r, shared_r)
    increments = _extra_increments(away, home, extra)
    pmf: dict[tuple[int, int], float] = {}
    tie = 0.0
    for i, row in enumerate(reg):
        for j, p in enumerate(row):
            if p == 0.0:
                continue
            if i != j:
                pmf[(i, j)] = pmf.get((i, j), 0.0) + p
                continue
            tie += p
            for (da, dh), q in increments.items():
                key = (i + da, i + dh)
                pmf[key] = pmf.get(key, 0.0) + p * q
    total = sum(pmf.values())
    if not abs(total - 1.0) < 1e-7:
        raise JointTeamRunsError("JOINT_PMF_DOES_NOT_CONSERVE")
    if any(a == h for a, h in pmf):
        raise JointTeamRunsError("FINAL_TIE_STATE_PRESENT")
    joint = {f"{a},{h}": p / total for (a, h), p in sorted(pmf.items()) if p > 0.0}
    identity = {
        "version": VERSION, "mode": mode, "away_mean_runs": away, "home_mean_runs": home,
        "team_dispersion_r": team_r, "shared_pace_r": shared_r, "extra_half_inning_mean": extra,
    }
    return {
        **identity,
        "joint_score_pmf": joint,
        "regulation_tie_probability": tie,
        "result_sha256": canonical_json_sha256({**identity, "pmf": joint}),
        "research_only": True,
        "eligible": False,
        "status": "RESEARCH_UNVALIDATED_NOT_REGISTERED",
    }


def read_market(distribution: Mapping[str, Any], *, market: str, side: str, line: Any = None,
                team_side: str | None = None) -> dict[str, Any]:
    """Settle one selection through the production readout (shared semantics)."""
    r = read_game_probability(distribution, market=market, line=line, side=side, team_side=team_side)
    return {"market": r.market, "side": r.side, "line": r.line, "team_side": r.team_side,
            "probability": r.probability, "push_probability": r.push_probability,
            "readout_sha256": r.readout_sha256, "research_only": True, "eligible": False}


def ladder(distribution: Mapping[str, Any], *, market: str, side: str, lines: list[float],
           team_side: str | None = None) -> list[dict[str, Any]]:
    return [read_market(distribution, market=market, side=side, line=x, team_side=team_side) for x in lines]


def marginal_means(distribution: Mapping[str, Any]) -> tuple[float, float]:
    a = h = 0.0
    for key, p in distribution["joint_score_pmf"].items():
        x, y = (int(v) for v in key.split(","))
        a += x * p
        h += y * p
    return a, h
