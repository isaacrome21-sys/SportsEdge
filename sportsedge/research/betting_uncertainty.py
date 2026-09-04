"""Season-cluster uncertainty for historical SportsEdge betting evidence.

This module complements ``multi_market_backtest``. It evaluates a frozen set of
already-selected bets and never selects bets, changes edge floors, or grants
production eligibility.
"""
from __future__ import annotations

from math import isfinite
from random import Random
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence

from .multi_market_backtest import (
    BinaryResearchRow,
    ResearchBacktestError,
    canonicalize_rows,
)


def _quantile(values: Sequence[float], q: float) -> float:
    if not values:
        raise ResearchBacktestError("EMPTY_QUANTILE")
    if not 0.0 <= q <= 1.0:
        raise ResearchBacktestError("QUANTILE_OUT_OF_RANGE")
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    lo = int(pos)
    hi = min(len(ordered) - 1, lo + 1)
    frac = pos - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def _pnl(row: BinaryResearchRow) -> float:
    if row.offered_decimal is None:
        raise ResearchBacktestError("OFFERED_DECIMAL_REQUIRED_FOR_PNL")
    if row.outcome is None:
        return 0.0
    if row.outcome == 1:
        return float(row.offered_decimal) - 1.0
    return -1.0


def _metrics(rows: Sequence[BinaryResearchRow]) -> dict[str, float | int | None]:
    if not rows:
        raise ResearchBacktestError("EMPTY_SELECTED_BET_ROWS")
    pnl = [_pnl(row) for row in rows]
    clv = [float(row.clv_pct) for row in rows if row.clv_pct is not None]
    resolved = [row for row in rows if row.outcome in (0, 1)]
    wins = sum(row.outcome == 1 for row in resolved)
    return {
        "n": len(rows),
        "resolved_n": len(resolved),
        "push_void_n": sum(row.outcome is None for row in rows),
        "profit_units": sum(pnl),
        "roi": sum(pnl) / len(rows),
        "resolved_win_rate": wins / len(resolved) if resolved else None,
        "avg_clv_pct": mean(clv) if clv else None,
    }


def selected_betting_bootstrap(
    rows: Iterable[Mapping[str, Any] | BinaryResearchRow], *,
    reps: int = 2000,
    seed: int = 20260903,
) -> dict[str, Any]:
    """Bootstrap frozen bet performance by season cluster.

    Resampling whole seasons preserves within-season dependence better than a
    naive independent-bet bootstrap. ROI includes pushes/voids as zero PnL.
    """
    if isinstance(reps, bool) or int(reps) <= 0:
        raise ResearchBacktestError("BOOTSTRAP_REPS_INVALID")
    data = [
        row for row in canonicalize_rows(rows)
        if row.selected and row.offered_decimal is not None
    ]
    if not data:
        raise ResearchBacktestError("NO_SELECTED_PRICED_BETS")
    seasons = sorted({row.season for row in data})
    if len(seasons) < 2:
        raise ResearchBacktestError("BETTING_BOOTSTRAP_REQUIRES_MULTIPLE_SEASONS")
    by_season: dict[int, list[BinaryResearchRow]] = {}
    for row in data:
        by_season.setdefault(row.season, []).append(row)

    point = _metrics(data)
    rng = Random(int(seed))
    roi_samples: list[float] = []
    profit_samples: list[float] = []
    clv_samples: list[float] = []
    win_rate_samples: list[float] = []
    for _ in range(int(reps)):
        sample: list[BinaryResearchRow] = []
        for _ in seasons:
            picked = seasons[rng.randrange(len(seasons))]
            sample.extend(by_season[picked])
        metrics = _metrics(sample)
        roi_samples.append(float(metrics["roi"]))
        profit_samples.append(float(metrics["profit_units"]))
        if metrics["avg_clv_pct"] is not None:
            clv_samples.append(float(metrics["avg_clv_pct"]))
        if metrics["resolved_win_rate"] is not None:
            win_rate_samples.append(float(metrics["resolved_win_rate"]))

    def ci(values: Sequence[float]) -> list[float] | None:
        if not values:
            return None
        return [_quantile(values, 0.025), _quantile(values, 0.975)]

    result = {
        **point,
        "roi_ci95": ci(roi_samples),
        "profit_units_ci95": ci(profit_samples),
        "resolved_win_rate_ci95": ci(win_rate_samples),
        "avg_clv_pct_ci95": ci(clv_samples),
        "bootstrap_cluster": "season",
        "bootstrap_reps": int(reps),
        "bootstrap_seed": int(seed),
    }
    numeric = [
        result["roi"], result["profit_units"],
        *([] if result["avg_clv_pct"] is None else [result["avg_clv_pct"]]),
    ]
    if any(not isfinite(float(value)) for value in numeric):
        raise ResearchBacktestError("BETTING_UNCERTAINTY_NONFINITE")
    return result
