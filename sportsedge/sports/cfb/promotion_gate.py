"""CFB promotion gate under ruling 2026-10-23i (research-only).

A market is POTENTIAL_PLAY only when its out-of-sample gate metrics show the
whole 95% CI of (model Brier - closing no-vig market Brier) strictly below 0
on at least MIN_OOS_N games. Anything missing or malformed is RESEARCH_ONLY.
Even POTENTIAL_PLAY never sets play_allowed: that requires validation that
does not exist yet. All output stays SCREEN/NOT_VALIDATED.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

RULING = "2026-10-23i"
MIN_OOS_N = 300


def market_status(gate: Mapping[str, Any], market: str) -> str:
    try:
        if gate.get("ruling") != RULING:
            return "RESEARCH_ONLY"
        split = str(gate.get("split") or "").lower()
        if "out of sample" not in split or "closing" not in split:
            return "RESEARCH_ONLY"
        m = (gate.get("markets") or {}).get(market)
        if not isinstance(m, Mapping):
            return "RESEARCH_ONLY"
        n = m.get("n")
        ci = m.get("diff_ci95")
        if isinstance(n, bool) or not isinstance(n, int) or n < MIN_OOS_N:
            return "RESEARCH_ONLY"
        if not isinstance(ci, (list, tuple)) or len(ci) != 2:
            return "RESEARCH_ONLY"
        lo, hi = ci
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (lo, hi)):
            return "RESEARCH_ONLY"
        if lo > hi:
            return "RESEARCH_ONLY"
        return "POTENTIAL_PLAY" if hi < 0 else "RESEARCH_ONLY"
    except Exception:
        return "RESEARCH_ONLY"


def card_label(gate: Mapping[str, Any], market: str) -> dict:
    return {"market": market, "promotion": market_status(gate, market), "ruling": RULING,
            "status_label": "SCREEN/NOT_VALIDATED", "play_allowed": False}
