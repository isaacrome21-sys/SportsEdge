from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable, Mapping

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


def _strict_bool(value: Any, *, field: str) -> bool:
    if type(value) is not bool:
        raise DevigError(f"{field} must be bool")
    return value


def _base_identity(quote: Mapping[str, Any]) -> tuple[str, str, str, str, bool]:
    try:
        alternate = _strict_bool(quote.get("is_alternate", False), field="is_alternate")
        return (
            str(quote["game_id"]),
            str(quote.get("period", "FG")),
            str(quote["market"]),
            str(quote.get("book_key", "")),
            alternate,
        )
    except DevigError:
        raise
    except Exception as exc:
        raise DevigError("paired quote identity incomplete") from exc


def _line(quote: Mapping[str, Any]) -> float:
    try:
        line = float(quote["line"])
    except Exception as exc:
        raise DevigError("paired quote line invalid") from exc
    if not isfinite(line):
        raise DevigError("paired quote line must be finite")
    return line


def _normalize_side(value: Any) -> str:
    side = str(value or "").upper()
    return {
        "HOME_ML": "HOME", "AWAY_ML": "AWAY",
        "HOME_RL": "HOME", "AWAY_RL": "AWAY",
    }.get(side, side)


def _complementary_sides(a: str, b: str) -> bool:
    pair = {_normalize_side(a), _normalize_side(b)}
    return pair in ({"OVER", "UNDER"}, {"HOME", "AWAY"}, {"YES", "NO"})


def validate_pair(candidate: Mapping[str, Any], opposite: Mapping[str, Any]) -> None:
    """Market-aware two-way price pairing.

    MONEYLINE/RUN_LINE bind opposing team entity IDs. Totals, team totals,
    and player props bind the same entity. The old one-size identity tuple
    falsely rejected every legitimate ML/RL pair by requiring same entity.
    """
    if _base_identity(candidate) != _base_identity(opposite):
        raise DevigError("paired quote identity mismatch")
    market = str(candidate.get("market", "")).upper()
    if market != str(opposite.get("market", "")).upper():
        raise DevigError("paired quote market mismatch")
    if not _complementary_sides(candidate.get("side", ""), opposite.get("side", "")):
        raise DevigError("paired quote sides are not complementary")
    a_entity = str(candidate.get("entity_id", "")); b_entity = str(opposite.get("entity_id", ""))
    if not a_entity or not b_entity:
        raise DevigError("paired quote entity identity incomplete")

    if market in {"MONEYLINE", "F5_MONEYLINE"}:
        if {_normalize_side(candidate.get("side")), _normalize_side(opposite.get("side"))} != {"HOME", "AWAY"}:
            raise DevigError("moneyline pair must be HOME/AWAY")
        if a_entity == b_entity:
            raise DevigError("moneyline pair must bind opposing team entities")
        return

    if market in {"RUN_LINE", "F5_RUN_LINE"}:
        if {_normalize_side(candidate.get("side")), _normalize_side(opposite.get("side"))} != {"HOME", "AWAY"}:
            raise DevigError("run-line pair must be HOME/AWAY")
        if a_entity == b_entity:
            raise DevigError("run-line pair must bind opposing team entities")
        if _line(candidate) != -_line(opposite):
            raise DevigError("run-line pair must use opposite signed thresholds")
        return

    if a_entity != b_entity:
        raise DevigError("paired quote entity mismatch")
    if _line(candidate) != _line(opposite):
        raise DevigError("paired quote line mismatch")


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
    """Remove two-sided margin by normalizing raw implied probabilities to sum to one."""
    validate_pair(candidate, opposite)
    q1 = _raw_implied(candidate.get("american_odds")); q2 = _raw_implied(opposite.get("american_odds"))
    total = q1 + q2
    if not isfinite(total) or total <= 0:
        raise DevigError("invalid paired implied-probability sum")
    p1 = q1 / total; p2 = q2 / total
    return DevigResult(method="MULTIPLICATIVE_V1", candidate_raw_implied=q1,
                       opposite_raw_implied=q2, overround=total - 1.0,
                       candidate_fair_probability=p1, opposite_fair_probability=p2)
