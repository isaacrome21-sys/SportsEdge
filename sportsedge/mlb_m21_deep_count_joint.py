"""Research-only first-inning count joint, not an admitted NRFI/YRFI model.

IMPORTANT: The first-inning Poisson count sibling previously LOST to the
binary first-inning model on the binary outcome, and remains an adverse
baseline record. This is a deliberately independent-Poisson count
CHALLENGER, with unverified historical calibration and NO market test.
Existing M21 NO_ENGINE gates stay untouched.

Both first-inning halves are assumed independent conditional on prior
offense/allow marginal rates. This is a modeling assumption, not a
measured or verified cross-half dependence structure. It cannot be
used to price a wager or override the canonical binary engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite
from typing import Any, Mapping, Sequence

from .mlb_first_inning_model import _pool, blended_rate, FirstInningModelError
from .mlb_empirical_bayes import JEFFREYS_ALPHA, posterior_settlement_mass
from .source_lineage import canonical_json_sha256

VERSION = "mlb_m21_first_inning_independent_poisson_count_joint_v1"
READOUT_VERSION = "mlb_m21_first_inning_count_derived_v1_jeffreys"
MARKETS = frozenset({
    "FIRST_INNING_3_WAY", "FIRST_INNING_RUN_LINE",
    "FIRST_INNING_ODD_EVEN",
})
TAIL_TOLERANCE = 1e-13
MAX_SUPPORT = 256
MAX_LAMBDA = 30.0


class M21CountError(ValueError):
    """Fail-closed named refusal."""


@dataclass(frozen=True)
class M21Joint:
    joint_score_pmf: dict[str, float]
    lambda_away: float
    lambda_home: float
    away_history_games: int
    home_history_games: int
    source_evidence_sha256: str
    distribution_sha256: str
    tail_mass_truncated: float
    version: str = VERSION
    conditional_independence_assumed: bool = True
    documented_binary_baseline_loss: bool = True
    eligible: bool = False
    research_only: bool = True
    market_test: str = "NO_MARKET_TEST"


@dataclass(frozen=True)
class M21Readout:
    market: str
    selection: str
    line: float | None
    probability: float
    push_probability: float
    source_distribution_sha256: str
    readout_sha256: str
    readout_version: str = READOUT_VERSION
    status: str = "RESEARCH_CHALLENGER_KNOWN_BINARY_BASELINE_LOSS"
    conditional_independence_assumed: bool = True
    documented_binary_baseline_loss: bool = True
    eligible: bool = False
    research_only: bool = True
    market_test: str = "NO_MARKET_TEST"
    play_authority: bool = False
    staking_authority: bool = False


def _poisson(lam: float) -> tuple[dict[int, float], float]:
    if not isfinite(lam) or not 0 < lam <= MAX_LAMBDA:
        raise M21CountError("FIRST_INNING_LAMBDA_OUT_OF_RESEARCH_SUPPORT")
    mass = exp(-lam)
    values = {0: mass}
    total = mass
    for k in range(1, MAX_SUPPORT + 1):
        mass = mass * lam / k
        values[k] = mass
        total += mass
        if 1 - total <= TAIL_TOLERANCE:
            break
    remainder = max(0.0, 1 - total)
    if remainder > TAIL_TOLERANCE:
        raise M21CountError("UNRESOLVED_POISSON_TAIL_MASS")
    # The omitted tail is bounded at 1e-13. Normalization is explicit;
    # the output stores the upper bound so it is not silently missing.
    return {k: p / total for k, p in values.items()}, remainder


def construct_first_inning_joint(
    *, away_for: Sequence[int], home_against: Sequence[int],
    home_for: Sequence[int], away_against: Sequence[int],
    source_evidence_sha256: str,
) -> M21Joint:
    """Standalone research construction from independently admitted pools.

    The SHA is a caller-provided lineage claim, NOT cryptographic proof
    that the pool is complete, pregame, or sourced authentically. The
    caller must independently verify PIT/team/game identity first.
    """
    digest = str(source_evidence_sha256 or "")
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest.lower()):
        raise M21CountError("PINNED_SOURCE_EVIDENCE_SHA256_REQUIRED")
    try:
        a_for = _pool(away_for, "away_for")
        h_allowed = _pool(home_against, "home_against")
        h_for = _pool(home_for, "home_for")
        a_allowed = _pool(away_against, "away_against")
    except FirstInningModelError as exc:
        raise M21CountError(f"INCUMBENT_POOL_REJECTED:{exc}") from exc
    lam_a = blended_rate(a_for, h_allowed)
    lam_h = blended_rate(h_for, a_allowed)
    a_pmf, a_tail = _poisson(lam_a)
    h_pmf, h_tail = _poisson(lam_h)
    joint = {
        f"{a},{h}": a_mass * h_mass
        for a, a_mass in sorted(a_pmf.items())
        for h, h_mass in sorted(h_pmf.items())
    }
    if abs(sum(joint.values()) - 1.0) > 1e-12:
        raise M21CountError("FIRST_INNING_JOINT_NOT_CONSERVED")
    payload = {
        "version": VERSION, "independence_assumed": True,
        "known_binary_baseline_loss": True,
        "source_evidence_sha256": digest.lower(),
        "lambda_away": lam_a, "lambda_home": lam_h,
        "joint_score_pmf": joint,
        "away_history_games": len(a_for),
        "home_history_games": len(h_for),
        "tail_mass_truncated": a_tail + h_tail,
    }
    return M21Joint(
        joint_score_pmf=joint,
        lambda_away=lam_a, lambda_home=lam_h,
        away_history_games=len(a_for), home_history_games=len(h_for),
        source_evidence_sha256=digest.lower(),
        distribution_sha256=canonical_json_sha256(payload),
        tail_mass_truncated=a_tail + h_tail,
    )


def _states(joint: M21Joint):
    if not isinstance(joint, M21Joint):
        raise M21CountError("M21_COUNT_JOINT_REQUIRED")
    if not joint.conditional_independence_assumed or (
            not joint.documented_binary_baseline_loss):
        raise M21CountError("REQUIRED_ADVERSE_ASSUMPTIONS_NOT_DISCLOSED")
    if len(joint.distribution_sha256) != 64:
        raise M21CountError("M21_DISTRIBUTION_SHA_REQUIRED")
    rows = []
    total = 0.0
    for key, raw in joint.joint_score_pmf.items():
        try:
            a, h = key.split(",")
            ai, hi, p = int(a), int(h), float(raw)
        except (AttributeError, ValueError, TypeError) as exc:
            raise M21CountError("INVALID_JOINT_SCORE_CELL") from exc
        if key != f"{ai},{hi}" or min(ai, hi) < 0 or (
                not isfinite(p)) or p < 0:
            raise M21CountError("INVALID_JOINT_SCORE_CELL")
        rows.append((ai, hi, p))
        total += p
    if not rows or abs(total - 1.0) > 1e-12:
        raise M21CountError("M21_DISTRIBUTION_MASS_NOT_CONSERVED")
    return rows


def read_first_inning_deep(joint: M21Joint, *, market: str,
                           selection: str, line: Any = None) -> M21Readout:
    """Research-only settlement readout. No bookmaker identity admitted."""
    name = str(market or "").strip().upper()
    side = str(selection or "").strip().upper()
    if name not in MARKETS:
        raise M21CountError("UNSUPPORTED_FIRST_INNING_DEEP_MARKET")
    rows = _states(joint)
    n = float(min(joint.away_history_games, joint.home_history_games))
    if n < 10:
        raise M21CountError("INSUFFICIENT_FIRST_INNING_HISTORY")
    line_out = None
    if name == "FIRST_INNING_3_WAY":
        if side not in {"HOME", "AWAY", "TIE"} or line is not None:
            raise M21CountError("FIRST_INNING_THREE_WAY_HOME_TIE_AWAY_REQUIRED")
        raw = {
            "HOME": sum(p for a, h, p in rows if h > a),
            "AWAY": sum(p for a, h, p in rows if a > h),
            "TIE": sum(p for a, h, p in rows if a == h),
        }
        if abs(sum(raw.values()) - 1.0) > 1e-12:
            raise M21CountError("THREE_WAY_FIRST_INNING_MASS_NOT_CONSERVED")
        alpha = {k: JEFFREYS_ALPHA + n * v for k, v in raw.items()}
        probability = alpha[side] / sum(alpha.values())
        push = 0.0
    elif name == "FIRST_INNING_ODD_EVEN":
        if side not in {"ODD", "EVEN"} or line is not None:
            raise M21CountError("FIRST_INNING_PARITY_ODD_EVEN_REQUIRED")
        mass = sum(p for a, h, p in rows if (a + h) % 2)
        posterior = posterior_settlement_mass(
            over_mass=mass, under_mass=1 - mass, push_mass=0.0,
            effective_n=n, has_push=False)
        probability = posterior["p_over" if side == "ODD" else "p_under"]
        push = 0.0
    else:
        if side not in {"HOME", "AWAY"}:
            raise M21CountError("FIRST_INNING_RUN_LINE_HOME_AWAY_REQUIRED")
        if isinstance(line, bool) or line is None:
            raise M21CountError("FIRST_INNING_RUN_LINE_REQUIRED")
        try:
            line_out = float(line)
        except (ValueError, TypeError) as exc:
            raise M21CountError("FIRST_INNING_RUN_LINE_INVALID") from exc
        if not isfinite(line_out) or not -20 <= line_out <= 20:
            raise M21CountError("FIRST_INNING_RUN_LINE_INVALID")
        margin = [((h - a) if side == "HOME" else (a - h)) + line_out
                  for a, h, _ in rows]
        win = sum(p for (_, _, p), x in zip(rows, margin) if x > 0)
        tie = sum(p for (_, _, p), x in zip(rows, margin) if x == 0)
        lose = sum(p for (_, _, p), x in zip(rows, margin) if x < 0)
        posterior = posterior_settlement_mass(
            over_mass=win, under_mass=lose, push_mass=tie,
            effective_n=n, has_push=line_out.is_integer())
        probability, push = posterior["p_over"], posterior["p_push"]
    evidence = {
        "version": READOUT_VERSION, "source_distribution_sha256": joint.distribution_sha256,
        "market": name, "selection": side, "line": line_out,
        "probability": float(probability), "push_probability": float(push),
        "conditional_independence_assumed": True,
        "documented_binary_baseline_loss": True,
    }
    return M21Readout(
        market=name, selection=side, line=line_out,
        probability=float(probability), push_probability=float(push),
        source_distribution_sha256=joint.distribution_sha256,
        readout_sha256=canonical_json_sha256(evidence))
