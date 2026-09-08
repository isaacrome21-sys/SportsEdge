from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable, Mapping

from .mlb_market_binding_v13 import (
    runtime_quote_binding_row,
    validate_quote_pair,
)
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


def _raw_implied(odds: Any) -> float:
    return 1.0 / american_to_decimal(odds)


def validate_pair(candidate: Mapping[str, Any], opposite: Mapping[str, Any]) -> None:
    """Validate a same-book two-way pair using the hardened market contract.

    In particular, ML/RL pairs are opposing TEAM entities, while totals/player
    props are same-entity pairs.  The old generic identity tuple falsely
    rejected legitimate HOME-vs-AWAY moneylines and +/-1.5 run lines.
    """
    try:
        validate_quote_pair(
            runtime_quote_binding_row(candidate),
            runtime_quote_binding_row(opposite),
        )
    except Exception as exc:
        raise DevigError(f"paired quote binding invalid: {exc}") from exc


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


def multiplicative_devig(candidate: Mapping[str, Any], opposite: Mapping[str, Any]) -> DevigResult:
    validate_pair(candidate, opposite)
    q1 = _raw_implied(candidate.get("american_odds"))
    q2 = _raw_implied(opposite.get("american_odds"))
    total = q1 + q2
    if not isfinite(total) or total <= 0:
        raise DevigError("invalid paired implied-probability sum")
    p1 = q1 / total
    p2 = q2 / total
    return DevigResult("MULTIPLICATIVE_V1", q1, q2, total - 1.0, p1, p2)
