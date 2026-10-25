"""Per-market evidence ladder status, read by every card.

File: ``config/market_ladder_status.json``. Key: ``"<SPORT>:<MARKET>"``.
A market missing from the file is PAPER. There is no inheritance between
markets or sports. This module only reads status and reports what the
evidence would support; it never writes or promotes.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from statistics import mean
from typing import Any

LADDER_PATH = Path(__file__).resolve().parents[2] / "config" / "market_ladder_status.json"
PAPER, STAKE_025, STAKE_05 = "PAPER", "STAKE_0_25U", "STAKE_0_5U"
STATUSES = (PAPER, STAKE_025, STAKE_05)
STAKE_UNITS = {PAPER: 0.0, STAKE_025: 0.25, STAKE_05: 0.5}
MIN_GRADED = 200  # Lane 7 gate: n>=200, mean no-vig CLV > 0, ROI > 0


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


def evidence_supports(clv_values: Iterable[float], current: str = PAPER, *,
                      units: Iterable[float] | None = None) -> str:
    """Status the graded evidence would support (report only, never applied).

    Same bar as the Lane 7 gate: PAPER -> 0.25u needs >= 200 graded picks in
    this market with mean no-vig CLV > 0 AND realized ROI > 0 (``units`` is the
    per-pick graded units, same picks as ``clv_values``). Missing or mismatched
    ``units`` stays PAPER. 0.25u -> 0.5u only if all of that still holds.
    """
    values = list(clv_values)
    results = list(units) if units is not None else []
    if len(values) < MIN_GRADED or len(results) != len(values):
        return PAPER
    if mean(values) <= 0 or sum(results) <= 0:
        return PAPER
    return STAKE_05 if current in (STAKE_025, STAKE_05) else STAKE_025
