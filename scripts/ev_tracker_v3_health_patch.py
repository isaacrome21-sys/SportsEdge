"""Compatibility helper for ev_tracker health output under V3.

A caller that has no credits or a dead/unauthorized credential must return DEGRADED, never OK.
"""
from __future__ import annotations
from typing import Iterable

OK, DEGRADED = 0, 3


def exit_code(*, remaining_credits: int | None, error_codes: Iterable[str] = (), dead_slots: int = 0) -> int:
    codes = set(error_codes)
    if dead_slots > 0:
        return DEGRADED
    if remaining_credits is not None and remaining_credits <= 0:
        return DEGRADED
    if "ODDS_API_UNAUTHORIZED" in codes or "ODDS_API_FORBIDDEN" in codes:
        return DEGRADED
    return OK
