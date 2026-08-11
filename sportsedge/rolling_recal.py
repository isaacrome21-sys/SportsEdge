"""Validated rolling-window league-rate recalibration for era drift."""
from __future__ import annotations

from datetime import date as Date

WINDOW_DAYS = 45
SHRINKAGE = 400
CODE_VERSION = "rolling_recal_v1.0"


def _to_date(s: str) -> Date:
    return Date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def build_rolling_league_rate(daily_num: dict, daily_den: dict, window_days: int = WINDOW_DAYS, min_den: int = 2000) -> dict:
    dates = sorted(daily_den.keys())
    date_objs = {d: _to_date(d) for d in dates}
    rolling = {}
    for i, d in enumerate(dates):
        cutoff = date_objs[d]
        num = 0
        den = 0
        for d2 in dates[:i]:
            if (cutoff - date_objs[d2]).days <= window_days:
                num += daily_num.get(d2, 0)
                den += daily_den.get(d2, 0)
        rolling[d] = (num / den) if den > min_den else None
    return rolling


def recalibrated_rate(entity_num: int, entity_den: int, rolling_league_rate: float, shrinkage: int = SHRINKAGE, lo: float = 0.005, hi: float = 0.30) -> float:
    rate = (entity_num + rolling_league_rate * shrinkage) / (entity_den + shrinkage)
    return min(max(rate, lo), hi)
