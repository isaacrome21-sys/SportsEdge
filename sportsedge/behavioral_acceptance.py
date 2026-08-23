"""Behavioral acceptance diagnostics for model challengers.

This module deliberately does not choose promotion thresholds. It converts line-level
reference comparisons into deterministic evidence: error, support, monotonicity and
sign behavior. Promotion remains an explicit contract decision.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from math import isfinite
from typing import Any, Iterable, Mapping


class BehavioralAcceptanceError(ValueError):
    pass


@dataclass(frozen=True)
class BehavioralRow:
    market: str
    line: float
    side: str
    reference_p: float
    incumbent_p: float
    challenger_p: float
    expected_count: float | None = None
    support_violation_p: float = 0.0
    band: str | None = None

    @property
    def incumbent_error(self) -> float:
        return self.incumbent_p - self.reference_p

    @property
    def challenger_error(self) -> float:
        return self.challenger_p - self.reference_p

    @property
    def incumbent_abs_error(self) -> float:
        return abs(self.incumbent_error)

    @property
    def challenger_abs_error(self) -> float:
        return abs(self.challenger_error)


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise BehavioralAcceptanceError(f"{name} must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise BehavioralAcceptanceError(f"{name} must be numeric") from exc
    if not isfinite(out):
        raise BehavioralAcceptanceError(f"{name} must be finite")
    return out


def _prob(value: Any, name: str) -> float:
    out = _finite(value, name)
    if not 0.0 <= out <= 1.0:
        raise BehavioralAcceptanceError(f"{name} must be in [0,1]")
    return out


def normalize_row(raw: Mapping[str, Any]) -> BehavioralRow:
    market = str(raw.get("market", "")).strip().upper()
    side = str(raw.get("side", "")).strip().upper()
    if not market:
        raise BehavioralAcceptanceError("market required")
    if not side:
        raise BehavioralAcceptanceError("side required")
    expected = raw.get("expected_count")
    expected_count = None if expected is None else _finite(expected, "expected_count")
    if expected_count is not None and expected_count < 0:
        raise BehavioralAcceptanceError("expected_count must be >= 0")
    support = _prob(raw.get("support_violation_p", 0.0), "support_violation_p")
    return BehavioralRow(
        market=market,
        line=_finite(raw.get("line"), "line"),
        side=side,
        reference_p=_prob(raw.get("reference_p"), "reference_p"),
        incumbent_p=_prob(raw.get("incumbent_p"), "incumbent_p"),
        challenger_p=_prob(raw.get("challenger_p"), "challenger_p"),
        expected_count=expected_count,
        support_violation_p=support,
        band=None if raw.get("band") is None else str(raw.get("band")),
    )


def _sign(value: float, tol: float = 1e-12) -> int:
    if value > tol:
        return 1
    if value < -tol:
        return -1
    return 0


def _sign_reversal_count(rows: list[BehavioralRow], attr: str) -> int:
    """Count adjacent-line error sign reversals within the same market/side/band/rate."""
    groups: dict[tuple[str, str, str | None, float | None], list[BehavioralRow]] = {}
    for row in rows:
        key = (row.market, row.side, row.band, row.expected_count)
        groups.setdefault(key, []).append(row)
    reversals = 0
    for group in groups.values():
        ordered = sorted(group, key=lambda x: x.line)
        signs = [_sign(float(getattr(row, attr))) for row in ordered]
        for left, right in zip(signs, signs[1:]):
            if left and right and left != right:
                reversals += 1
    return reversals


def _monotonicity_violations(rows: list[BehavioralRow]) -> int:
    """Check count-rate monotonicity where expected_count observations are supplied.

    OVER probabilities should not fall as expected count rises; UNDER probabilities
    should not rise. Other side labels are intentionally ignored rather than guessed.
    """
    groups: dict[tuple[str, float, str], list[BehavioralRow]] = {}
    for row in rows:
        if row.expected_count is None or row.side not in {"OVER", "UNDER"}:
            continue
        groups.setdefault((row.market, row.line, row.side), []).append(row)
    violations = 0
    for (_, _, side), group in groups.items():
        ordered = sorted(group, key=lambda x: float(x.expected_count))
        for left, right in zip(ordered, ordered[1:]):
            if side == "OVER" and right.challenger_p + 1e-12 < left.challenger_p:
                violations += 1
            if side == "UNDER" and right.challenger_p - 1e-12 > left.challenger_p:
                violations += 1
    return violations


def analyze_challenger(raw_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [normalize_row(row) for row in raw_rows]
    if not rows:
        raise BehavioralAcceptanceError("at least one behavioral row is required")

    incumbent_mae = sum(row.incumbent_abs_error for row in rows) / len(rows)
    challenger_mae = sum(row.challenger_abs_error for row in rows) / len(rows)
    improved = sum(row.challenger_abs_error + 1e-12 < row.incumbent_abs_error for row in rows)
    worsened = sum(row.challenger_abs_error > row.incumbent_abs_error + 1e-12 for row in rows)
    tied = len(rows) - improved - worsened

    evidence_rows = []
    for row in rows:
        item = asdict(row)
        item.update({
            "incumbent_error": row.incumbent_error,
            "challenger_error": row.challenger_error,
            "incumbent_abs_error": row.incumbent_abs_error,
            "challenger_abs_error": row.challenger_abs_error,
            "absolute_error_improvement": row.incumbent_abs_error - row.challenger_abs_error,
        })
        evidence_rows.append(item)

    return {
        "schema_version": 1,
        "row_count": len(rows),
        "incumbent_mae": incumbent_mae,
        "challenger_mae": challenger_mae,
        "mae_improvement": incumbent_mae - challenger_mae,
        "incumbent_max_abs_error": max(row.incumbent_abs_error for row in rows),
        "challenger_max_abs_error": max(row.challenger_abs_error for row in rows),
        "improved_rows": improved,
        "worsened_rows": worsened,
        "tied_rows": tied,
        "max_support_violation_p": max(row.support_violation_p for row in rows),
        "incumbent_adjacent_line_sign_reversals": _sign_reversal_count(rows, "incumbent_error"),
        "challenger_adjacent_line_sign_reversals": _sign_reversal_count(rows, "challenger_error"),
        "challenger_monotonicity_violations": _monotonicity_violations(rows),
        "rows": evidence_rows,
    }
