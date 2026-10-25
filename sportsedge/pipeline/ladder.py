"""Per-market evidence ladder status, read by every card.

File: ``config/market_ladder_status.json``. Key: ``"<SPORT>:<MARKET>"``.
A market missing from the file is PAPER. There is no inheritance between
markets or sports. This module only reads status and reports what the
evidence would support; it never writes or promotes.
"""
from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from statistics import mean
from typing import Any

LADDER_PATH = Path(__file__).resolve().parents[2] / "config" / "market_ladder_status.json"
PAPER, STAKE_025, STAKE_05 = "PAPER", "STAKE_0_25U", "STAKE_0_5U"
STATUSES = (PAPER, STAKE_025, STAKE_05)
STAKE_UNITS = {PAPER: 0.0, STAKE_025: 0.25, STAKE_05: 0.5}
MIN_GRADED = 50  # Lane 7 gate (owner ruling 2026-10-25): n>=50, mean no-vig CLV > 0, ROI > 0


class LadderError(ValueError):
    pass


def load_ladder(path: str | Path = LADDER_PATH) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for key, entry in (data.get("markets") or {}).items():
        if entry.get("status") not in STATUSES:
            raise LadderError(f"LADDER_STATUS_INVALID:{key}:{entry.get('status')}")
    return data


def market_key(sport: str, market: str) -> str:
    return f"{str(sport).upper()}:{market}"


def status_for(sport: str, market: str, *, ladder: Mapping[str, Any] | None = None) -> str:
    data = ladder if ladder is not None else load_ladder()
    entry = (data.get("markets") or {}).get(market_key(sport, market))
    return entry["status"] if entry else PAPER


def stake_units(sport: str, market: str, *, ladder: Mapping[str, Any] | None = None) -> float:
    return STAKE_UNITS[status_for(sport, market, ladder=ladder)]


def _finite_numbers(rows: Iterable[Any]) -> list[float] | None:
    """Every row must be a real finite int/float. Anything else -> None.

    Rejects NaN, +/-inf, bools, strings, None. One bad row voids the set,
    because NaN/inf make ``mean() <= 0`` and ``sum() <= 0`` compare False.
    """
    out: list[float] = []
    for value in rows:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        if not math.isfinite(number):
            return None
        out.append(number)
    return out


def evidence_supports(clv_values: Iterable[float], current: str = PAPER, *,
                      units: Iterable[float] | None = None) -> str:
    """Status the graded evidence would support (report only, never applied).

    Same bar as the Lane 7 gate: PAPER -> 0.25u needs >= 50 graded picks in
    this market with mean no-vig CLV > 0 AND realized ROI > 0 (``units`` is the
    per-pick graded units, same picks as ``clv_values``). Missing, mismatched,
    or non-finite rows stay PAPER. 0.25u -> 0.5u only if all of that still holds.
    """
    if units is None:
        return PAPER
    values = _finite_numbers(clv_values)
    results = _finite_numbers(units)
    if values is None or results is None:
        return PAPER
    if len(values) < MIN_GRADED or len(results) != len(values):
        return PAPER
    try:
        clv_mean, units_total = mean(values), math.fsum(results)
    except OverflowError:
        return PAPER
    if not (math.isfinite(clv_mean) and math.isfinite(units_total)):
        return PAPER
    if not (clv_mean > 0 and units_total > 0):
        return PAPER
    return STAKE_05 if current in (STAKE_025, STAKE_05) else STAKE_025


def span_filtered_evidence_supports(records: Iterable[Mapping[str, Any]], current: str = PAPER) -> str:
    """Report-only span filter; authentic quote/final receipts are separate checks.

    Missing span/method is never counted. Research rows may remain in the paper
    ledger, but cannot inflate n, mean CLV or realized units here.
    """
    from .picks import PickRecord, PickRecordError
    values, results, identity = [], [], None
    for row in records:
        try:
            pick = PickRecord.from_dict(row)
        except (PickRecordError, TypeError, ValueError, OverflowError):
            return PAPER
        key = (pick.sport, pick.market, pick.engine)
        if identity is None:
            identity = key
        elif key != identity:
            return PAPER  # no cross-market/version inheritance
        if pick.span_tier != 'FULL' or pick.capture_method not in ('PRIMARY_BROWSER','FALLBACK'):
            continue
        values.append(row.get('clv_prob'))
        results.append(row.get('units'))
    return evidence_supports(values, current, units=results)
