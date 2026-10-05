"""Fail-closed serving bridge for a successful NFL V2K Attempt 5 readout.

This module does not score or consume Attempt 5. It only accepts an already-produced
Attempt-5 result whose verdict is PASS and applies the frozen live parameters to a
current paired market. A FAIL/missing/malformed result cannot produce centers.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping

from .v2k_attempt5_market_calibration import (
    FAIR_SPREAD_SCALE,
    FAIR_TOTAL_SCALE,
    candidate_probability,
    fair_market_center,
)

RESULT_SCHEMA = "NFL_V2K_ATTEMPT5_DEVELOPMENT_VALIDATION_V1"


class Attempt5ServingError(ValueError):
    pass


def _num(value: Any, field: str) -> float:
    if value in (None, "") or isinstance(value, bool):
        raise Attempt5ServingError(field + ":NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise Attempt5ServingError(field + ":NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise Attempt5ServingError(field + ":FINITE_REQUIRED")
    return out


def _american_probability(value: Any, field: str) -> float:
    odds = _num(value, field)
    if odds == 0:
        raise Attempt5ServingError(field + ":NONZERO_REQUIRED")
    return (-odds / (-odds + 100.0)) if odds < 0 else (100.0 / (odds + 100.0))


def _novig(a: Any, b: Any, field: str) -> float:
    pa = _american_probability(a, field + ".a")
    pb = _american_probability(b, field + ".b")
    total = pa + pb
    if total <= 0:
        raise Attempt5ServingError(field + ":PAIR_INVALID")
    return pa / total


def validate_pass_result(result: Mapping[str, Any]) -> Mapping[str, Any]:
    if result.get("schema") != RESULT_SCHEMA:
        raise Attempt5ServingError("ATTEMPT5_RESULT_SCHEMA_INVALID")
    if result.get("candidate_family") != "NFL_MARKET_CALIBRATION_LINE_G5":
        raise Attempt5ServingError("ATTEMPT5_CANDIDATE_FAMILY_INVALID")
    if result.get("verdict") != "ATTEMPT5_PASS":
        raise Attempt5ServingError("ATTEMPT5_NOT_PASSED")
    if result.get("attempt_consumed") is not True:
        raise Attempt5ServingError("ATTEMPT5_CONSUMPTION_UNBOUND")
    if result.get("development_budget_exhausted_after_run") is not True:
        raise Attempt5ServingError("ATTEMPT5_BUDGET_FINALITY_UNBOUND")
    params = result.get("live_parameters")
    if not isinstance(params, Mapping):
        raise Attempt5ServingError("ATTEMPT5_LIVE_PARAMETERS_MISSING")
    if _num(params.get("fair_spread_scale"), "fair_spread_scale") != FAIR_SPREAD_SCALE:
        raise Attempt5ServingError("ATTEMPT5_FAIR_SPREAD_SCALE_DRIFT")
    if _num(params.get("fair_total_scale"), "fair_total_scale") != FAIR_TOTAL_SCALE:
        raise Attempt5ServingError("ATTEMPT5_FAIR_TOTAL_SCALE_DRIFT")
    return params


def centers_from_market(
    result: Mapping[str, Any],
    market: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply frozen PASS parameters to one current paired spread/total market."""
    params = validate_pass_result(result)

    spread_line = _num(market.get("spread_line"), "spread_line")
    total_line = _num(market.get("total_line"), "total_line")
    base_home_cover = _novig(
        market.get("home_spread_odds"),
        market.get("away_spread_odds"),
        "spread_prices",
    )
    base_over = _novig(
        market.get("over_odds"),
        market.get("under_odds"),
        "total_prices",
    )

    home_cover_p = candidate_probability(
        base_home_cover,
        spread_line,
        market="spread",
        intercept=_num(params.get("spread_intercept"), "spread_intercept"),
        line_beta=_num(params.get("spread_line_beta"), "spread_line_beta"),
    )
    over_p = candidate_probability(
        base_over,
        total_line,
        market="total",
        intercept=_num(params.get("total_intercept"), "total_intercept"),
        line_beta=_num(params.get("total_line_beta"), "total_line_beta"),
    )
    fair_margin = fair_market_center(line=spread_line, probability=home_cover_p, market="spread")
    fair_total = fair_market_center(line=total_line, probability=over_p, market="total")
    mean_home = (fair_total + fair_margin) / 2.0
    mean_away = (fair_total - fair_margin) / 2.0
    if mean_home <= 0 or mean_away <= 0:
        raise Attempt5ServingError("ATTEMPT5_NEGATIVE_TEAM_MEAN")

    return {
        "schema": "NFL_V2K_ATTEMPT5_SERVING_CENTERS_V1",
        "source": "NFL_MARKET_CALIBRATION_LINE_G5",
        "spread_line": spread_line,
        "total_line": total_line,
        "base_home_cover_probability": base_home_cover,
        "base_over_probability": base_over,
        "calibrated_home_cover_probability": home_cover_p,
        "calibrated_over_probability": over_p,
        "fair_margin": fair_margin,
        "fair_total": fair_total,
        "mean_home": mean_home,
        "mean_away": mean_away,
        "authority": {
            "attempt5_pass_required": True,
            "official": False,
            "staking": False,
        },
    }


__all__ = [
    "Attempt5ServingError",
    "RESULT_SCHEMA",
    "centers_from_market",
    "validate_pass_result",
]
