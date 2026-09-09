from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Any, Iterable, Mapping

from .edge_floors import FrozenDevigPolicy
from .truth_gate import american_to_decimal


class DevigError(ValueError):
    pass


@dataclass(frozen=True)
class DevigResult:
    method: str
    candidate_raw_implied: float
    opposite_raw_implied: float
    overround: float
    candidate_fair_probability: float
    opposite_fair_probability: float


@dataclass(frozen=True)
class PolicyDevigResult:
    selected: DevigResult
    longshot_triggered: bool
    sensitivity_results: tuple[DevigResult, ...]
    sensitivity_spread_probability_points: float
    haircut_probability_points: float
    fair_probability_for_decision: float


def _raw_implied(odds: Any) -> float:
    return 1.0 / american_to_decimal(odds)


def _american_numeric(odds: Any) -> float:
    # american_to_decimal owns validity semantics; this conversion is only for
    # the pre-frozen positive-longshot trigger.
    american_to_decimal(odds)
    try:
        value = float(odds)
    except (TypeError, ValueError) as exc:
        raise DevigError("american odds must be numeric") from exc
    if not isfinite(value):
        raise DevigError("american odds must be finite")
    return value


def _strict_bool(value: Any, *, field: str) -> bool:
    if type(value) is not bool:
        raise DevigError(f"{field} must be bool")
    return value


def _identity(quote: Mapping[str, Any]) -> tuple[str, str, str, str, str, bool]:
    try:
        alternate = _strict_bool(quote.get("is_alternate", False), field="is_alternate")
        return (
            str(quote["game_id"]),
            str(quote.get("period", "FG")),
            str(quote["market"]),
            str(quote["entity_id"]),
            str(quote.get("book_key", "")),
            alternate,
        )
    except DevigError:
        raise
    except Exception as exc:
        raise DevigError("paired quote identity incomplete") from exc


def _line_key(quote: Mapping[str, Any]) -> float:
    try:
        line = float(quote["line"])
    except Exception as exc:
        raise DevigError("paired quote line invalid") from exc
    if not isfinite(line):
        raise DevigError("paired quote line must be finite")
    market = str(quote.get("market", ""))
    if market in {"RUN_LINE", "F5_RUN_LINE"}:
        return abs(line)
    return line


def _complementary_sides(a: str, b: str) -> bool:
    pair = {a.upper(), b.upper()}
    return pair in (
        {"OVER", "UNDER"}, {"HOME", "AWAY"}, {"HOME_ML", "AWAY_ML"},
        {"HOME_RL", "AWAY_RL"}, {"YES", "NO"},
    )


def validate_pair(candidate: Mapping[str, Any], opposite: Mapping[str, Any]) -> None:
    if _identity(candidate) != _identity(opposite):
        raise DevigError("paired quote identity mismatch")
    if _line_key(candidate) != _line_key(opposite):
        raise DevigError("paired quote line mismatch")
    if not _complementary_sides(str(candidate.get("side", "")), str(opposite.get("side", ""))):
        raise DevigError("paired quote sides are not complementary")


def find_paired_quote(candidate: Mapping[str, Any], quotes: Iterable[Mapping[str, Any]]) -> Mapping[str, Any]:
    matches: list[Mapping[str, Any]] = []
    for quote in quotes:
        if quote is candidate or dict(quote) == dict(candidate):
            continue
        try:
            validate_pair(candidate, quote)
        except DevigError:
            continue
        matches.append(quote)
    if len(matches) != 1:
        raise DevigError(f"PAIRED_PRICE_REQUIRED_FOR_DEVIG: found={len(matches)}")
    return matches[0]


def _base_pair(candidate: Mapping[str, Any], opposite: Mapping[str, Any]) -> tuple[float, float, float]:
    validate_pair(candidate, opposite)
    q1 = _raw_implied(candidate.get("american_odds"))
    q2 = _raw_implied(opposite.get("american_odds"))
    total = q1 + q2
    if not isfinite(total) or total <= 0:
        raise DevigError("invalid paired implied-probability sum")
    if not (0 < q1 < 1) or not (0 < q2 < 1):
        raise DevigError("paired implied probabilities must be between zero and one")
    return q1, q2, total


def multiplicative_devig(candidate: Mapping[str, Any], opposite: Mapping[str, Any]) -> DevigResult:
    """Remove two-sided margin by normalizing raw implied probabilities to sum to one."""
    q1, q2, total = _base_pair(candidate, opposite)
    p1 = q1 / total
    p2 = q2 / total
    return DevigResult(
        method="MULTIPLICATIVE_V1",
        candidate_raw_implied=q1,
        opposite_raw_implied=q2,
        overround=total - 1.0,
        candidate_fair_probability=p1,
        opposite_fair_probability=p2,
    )


def power_devig(candidate: Mapping[str, Any], opposite: Mapping[str, Any]) -> DevigResult:
    """Two-way power devig: solve q1**k + q2**k = 1, then use q**k."""
    q1, q2, total = _base_pair(candidate, opposite)
    if abs(total - 1.0) <= 1e-15:
        exponent = 1.0
    else:
        low, high = 0.0, 100.0
        for _ in range(200):
            mid = (low + high) / 2.0
            value = (q1 ** mid) + (q2 ** mid) - 1.0
            if value > 0:
                low = mid
            else:
                high = mid
        exponent = (low + high) / 2.0
    p1 = q1 ** exponent
    p2 = q2 ** exponent
    norm = p1 + p2
    if not isfinite(norm) or abs(norm - 1.0) > 1e-10:
        raise DevigError("POWER_V1 failed probability normalization")
    return DevigResult(
        method="POWER_V1",
        candidate_raw_implied=q1,
        opposite_raw_implied=q2,
        overround=total - 1.0,
        candidate_fair_probability=p1 / norm,
        opposite_fair_probability=p2 / norm,
    )


def _shin_prob(q: float, total: float, z: float) -> float:
    denominator = 2.0 * (1.0 - z)
    if denominator <= 0:
        raise DevigError("SHIN_V1 invalid insider parameter")
    radicand = (z * z) + (4.0 * (1.0 - z) * (q * q) / total)
    return (sqrt(radicand) - z) / denominator


def shin_devig(candidate: Mapping[str, Any], opposite: Mapping[str, Any]) -> DevigResult:
    """Two-way Shin devig with the insider parameter solved by bisection."""
    q1, q2, total = _base_pair(candidate, opposite)
    if total < 1.0 - 1e-12:
        raise DevigError("SHIN_V1 requires nonnegative bookmaker overround")
    if abs(total - 1.0) <= 1e-15:
        p1, p2 = q1, q2
    else:
        low, high = 0.0, 1.0 - 1e-12
        f_low = _shin_prob(q1, total, low) + _shin_prob(q2, total, low) - 1.0
        f_high = _shin_prob(q1, total, high) + _shin_prob(q2, total, high) - 1.0
        if f_low < 0 or f_high > 0:
            raise DevigError("SHIN_V1 could not bracket insider parameter")
        for _ in range(200):
            mid = (low + high) / 2.0
            value = _shin_prob(q1, total, mid) + _shin_prob(q2, total, mid) - 1.0
            if value > 0:
                low = mid
            else:
                high = mid
        z = (low + high) / 2.0
        p1 = _shin_prob(q1, total, z)
        p2 = _shin_prob(q2, total, z)
    norm = p1 + p2
    if not isfinite(norm) or abs(norm - 1.0) > 1e-9:
        raise DevigError("SHIN_V1 failed probability normalization")
    return DevigResult(
        method="SHIN_V1",
        candidate_raw_implied=q1,
        opposite_raw_implied=q2,
        overround=total - 1.0,
        candidate_fair_probability=p1 / norm,
        opposite_fair_probability=p2 / norm,
    )


def devig_by_method(
    method: str, candidate: Mapping[str, Any], opposite: Mapping[str, Any]
) -> DevigResult:
    if method == "MULTIPLICATIVE_V1":
        return multiplicative_devig(candidate, opposite)
    if method == "POWER_V1":
        return power_devig(candidate, opposite)
    if method == "SHIN_V1":
        return shin_devig(candidate, opposite)
    raise DevigError(f"unsupported devig method: {method}")


def devig_with_policy(
    candidate: Mapping[str, Any],
    opposite: Mapping[str, Any],
    *,
    policy: FrozenDevigPolicy,
) -> PolicyDevigResult:
    """Apply the frozen estimator and fail closed on longshot method sensitivity.

    Sensitivity methods are not votes and are never reduced by a minimum-across-
    methods rule.  The configured estimator alone supplies the fair probability
    after the spread gate passes.
    """
    validate_pair(candidate, opposite)
    trigger = float(policy.longshot_trigger_american_odds)
    longshot = any(
        _american_numeric(row.get("american_odds")) >= trigger
        for row in (candidate, opposite)
    )
    haircut = float(policy.haircut_probability_points)

    if not longshot:
        selected = devig_by_method(policy.stable_candidate_estimator, candidate, opposite)
        fair = selected.candidate_fair_probability + haircut
        if not 0 < fair < 1:
            raise DevigError("DEVIG_HAIRCUT_PRODUCED_INVALID_FAIR_PROBABILITY")
        return PolicyDevigResult(
            selected=selected,
            longshot_triggered=False,
            sensitivity_results=(selected,),
            sensitivity_spread_probability_points=0.0,
            haircut_probability_points=haircut,
            fair_probability_for_decision=fair,
        )

    results = tuple(devig_by_method(m, candidate, opposite) for m in policy.sensitivity_methods)
    candidate_probs = [r.candidate_fair_probability for r in results]
    spread = max(candidate_probs) - min(candidate_probs)
    limit = float(policy.sensitivity_limit_absolute_probability_points)
    if spread > limit + 1e-15:
        raise DevigError(
            "LONGSHOT_DEVIG_SENSITIVITY_EXCEEDS_LIMIT:"
            f"spread={spread:.12f}:limit={limit:.12f}"
        )
    selected = next((r for r in results if r.method == policy.longshot_candidate_estimator), None)
    if selected is None:
        raise DevigError("LONGSHOT_DEVIG_ESTIMATOR_MISSING_FROM_SENSITIVITY_SET")
    fair = selected.candidate_fair_probability + haircut
    if not 0 < fair < 1:
        raise DevigError("DEVIG_HAIRCUT_PRODUCED_INVALID_FAIR_PROBABILITY")
    return PolicyDevigResult(
        selected=selected,
        longshot_triggered=True,
        sensitivity_results=results,
        sensitivity_spread_probability_points=spread,
        haircut_probability_points=haircut,
        fair_probability_for_decision=fair,
    )
