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
MIN_GRADED = 150


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


def evidence_supports(clv_values: Iterable[float], current: str = PAPER) -> str:
    """Status the graded CLV evidence would support (report only, never applied).

    PAPER -> 0.25u needs >= 150 graded picks with mean no-vig CLV > 0.
    0.25u -> 0.5u only if that still holds. Mean CLV <= 0 falls back to PAPER.
    """
    values = list(clv_values)
    if len(values) < MIN_GRADED or mean(values) <= 0:
        return PAPER
    return STAKE_05 if current in (STAKE_025, STAKE_05) else STAKE_025
