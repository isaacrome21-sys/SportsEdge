"""Slate-level MLB wager concentration guard.

This module is downstream of Model_P and the per-candidate Truth/Risk gates.  It
must never alter model probabilities or create a wager that was not already an
OFFICIAL_BET candidate.  Until the predeclared favorite/underdog calibration
protocol passes on forward evidence, it limits concentration in underdog side
positions without forcing favorite bets.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

PORTFOLIO_GUARD_VERSION = "MLB_PORTFOLIO_GUARD_V1_20260813"
MAX_DOG_ML_PER_SLATE = 1
MAX_DOG_SIDE_POSITIONS_PER_SLATE = 2
MAX_DOG_SIDE_KELLY_PER_SLATE = 0.020
SIDE_MARKETS = frozenset({"MONEYLINE", "RUN_LINE"})


def _copy(row: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["portfolio_guard_version"] = PORTFOLIO_GUARD_VERSION
    out.setdefault("pre_portfolio_bet_status", out.get("bet_status"))
    out.setdefault("portfolio_guard_reason", "PASS_THROUGH")
    return out


def _suppress(row: dict[str, Any], reason: str) -> None:
    row["bet_status"] = "PASS"
    row["kelly_fraction"] = 0.0
    row["portfolio_guard_reason"] = reason


def _underlying_ml(row: Mapping[str, Any]) -> float | None:
    raw = row.get("underlying_moneyline_odds")
    if raw is None and row.get("market") == "MONEYLINE":
        raw = row.get("american_odds")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _rank(row: Mapping[str, Any]) -> tuple[float, float, float, str, str]:
    """Deterministic ranking among already-qualified dog candidates only."""
    return (
        float(row.get("edge") or 0.0),
        float(row.get("ev_per_dollar") or 0.0),
        float(row.get("kelly_fraction") or 0.0),
        str(row.get("game_id") or ""),
        str(row.get("selection") or row.get("side") or ""),
    )


def apply_mlb_portfolio_guard(
    rows: Iterable[Mapping[str, Any]],
    *,
    dog_calibration_validated: bool = False,
) -> list[dict[str, Any]]:
    """Apply slate-level underdog concentration controls.

    When dog_calibration_validated is True this module records PASS_THROUGH and
    leaves already-official wager status/sizing unchanged.  Validation state
    must come from the separately attested calibration protocol; this function
    does not infer or calculate it.
    """
    out = [_copy(r) for r in rows]
    if dog_calibration_validated:
        for r in out:
            r["portfolio_guard_reason"] = "DOG_CALIBRATION_VALIDATED_PASS_THROUGH"
        return out

    dog_sides: list[dict[str, Any]] = []
    dog_mls: list[dict[str, Any]] = []
    for r in out:
        if r.get("bet_status") != "OFFICIAL_BET" or r.get("market") not in SIDE_MARKETS:
            continue
        ml = _underlying_ml(r)
        if ml is None or ml <= 100:
            continue
        dog_sides.append(r)
        if r.get("market") == "MONEYLINE":
            dog_mls.append(r)

    # Keep at most one underdog ML; do not manufacture a favorite replacement.
    if len(dog_mls) > MAX_DOG_ML_PER_SLATE:
        keep = max(dog_mls, key=_rank)
        for r in dog_mls:
            if r is keep:
                r["portfolio_guard_reason"] = "DOG_ML_CONCENTRATION_SELECTED"
            else:
                _suppress(r, "DOG_ML_CONCENTRATION_LIMIT")

    # Recompute after ML suppression and keep at most two underdog side positions.
    remaining = [
        r for r in out
        if r.get("bet_status") == "OFFICIAL_BET"
        and r.get("market") in SIDE_MARKETS
        and (_underlying_ml(r) or float("-inf")) > 100
    ]
    if len(remaining) > MAX_DOG_SIDE_POSITIONS_PER_SLATE:
        keep_ids = {id(r) for r in sorted(remaining, key=_rank, reverse=True)[:MAX_DOG_SIDE_POSITIONS_PER_SLATE]}
        for r in remaining:
            if id(r) in keep_ids:
                if r.get("portfolio_guard_reason") == "PASS_THROUGH":
                    r["portfolio_guard_reason"] = "DOG_SIDE_CONCENTRATION_SELECTED"
            else:
                _suppress(r, "DOG_SIDE_CONCENTRATION_LIMIT")

    # Cap aggregate dog-side Kelly guidance at 2% without changing wager status.
    remaining = [
        r for r in out
        if r.get("bet_status") == "OFFICIAL_BET"
        and r.get("market") in SIDE_MARKETS
        and (_underlying_ml(r) or float("-inf")) > 100
    ]
    total = sum(max(0.0, float(r.get("kelly_fraction") or 0.0)) for r in remaining)
    if total > MAX_DOG_SIDE_KELLY_PER_SLATE and total > 0:
        scale = MAX_DOG_SIDE_KELLY_PER_SLATE / total
        for r in remaining:
            r["kelly_fraction"] = max(0.0, float(r.get("kelly_fraction") or 0.0)) * scale
            suffix = "DOG_KELLY_SLATE_CAP"
            prior = str(r.get("portfolio_guard_reason") or "PASS_THROUGH")
            r["portfolio_guard_reason"] = f"{prior};{suffix}"

    return out
