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


def _legacy_identity(quote: Mapping[str, Any]) -> tuple[str, str, str, str, str, bool]:
    """Compatibility only for older non-production fixtures/paths.

    Production MLB card quotes carry event/game/team binding context and are
    validated by the hardened market-specific path below.
    """
    try:
        alternate = _strict_bool(quote.get("is_alternate", False), field="is_alternate")
        return (
            str(quote["game_id"]), str(quote.get("period", "FG")),
            str(quote["market"]), str(quote["entity_id"]),
            str(quote.get("book_key", "")), alternate,
        )
    except DevigError:
        raise
    except Exception as exc:
        raise DevigError("paired quote identity incomplete") from exc


def _legacy_line_key(quote: Mapping[str, Any]) -> float:
    try:
        line = float(quote["line"])
    except Exception as exc:
        raise DevigError("paired quote line invalid") from exc
    if not isfinite(line):
        raise DevigError("paired quote line must be finite")
    market = str(quote.get("market", ""))
    return abs(line) if market in {"RUN_LINE", "F5_RUN_LINE"} else line


def _legacy_complementary_sides(a: str, b: str) -> bool:
    pair = {a.upper(), b.upper()}
    return pair in (
        {"OVER", "UNDER"}, {"HOME", "AWAY"}, {"HOME_ML", "AWAY_ML"},
        {"HOME_RL", "AWAY_RL"}, {"YES", "NO"},
    )


def _has_hardened_binding_context(quote: Mapping[str, Any]) -> bool:
    return "event_id" in quote or "game_number" in quote or "event_home_team_id" in quote


def validate_pair(candidate: Mapping[str, Any], opposite: Mapping[str, Any]) -> None:
    """Validate a two-way pair.

    Hardened production quotes use market-aware semantics: ML/RL pair opposing
    team entities and run lines require opposite signs. Legacy fixture-only
    quotes keep their old identity contract so this change does not silently
    rewrite unrelated historical test inputs.
    """
    if _has_hardened_binding_context(candidate) or _has_hardened_binding_context(opposite):
        if not (_has_hardened_binding_context(candidate) and _has_hardened_binding_context(opposite)):
            raise DevigError("paired quote binding context mismatch")
        try:
            from .mlb_market_binding_v13 import runtime_quote_binding_row, validate_quote_pair
            validate_quote_pair(
                runtime_quote_binding_row(candidate),
                runtime_quote_binding_row(opposite),
            )
        except Exception as exc:
            raise DevigError(f"paired quote binding invalid: {exc}") from exc
        return

    if _legacy_identity(candidate) != _legacy_identity(opposite):
        raise DevigError("paired quote identity mismatch")
    if _legacy_line_key(candidate) != _legacy_line_key(opposite):
        raise DevigError("paired quote line mismatch")
    if not _legacy_complementary_sides(str(candidate.get("side", "")), str(opposite.get("side", ""))):
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


def multiplicative_devig(candidate: Mapping[str, Any], opposite: Mapping[str, Any]) -> DevigResult:
    """Remove two-sided margin by normalizing raw implied probabilities to one."""
    validate_pair(candidate, opposite)
    q1 = _raw_implied(candidate.get("american_odds"))
    q2 = _raw_implied(opposite.get("american_odds"))
    total = q1 + q2
    if not isfinite(total) or total <= 0:
        raise DevigError("invalid paired implied-probability sum")
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
