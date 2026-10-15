"""Strictly-prior empirical MLB first-3/first-7 runs research engine.

Research only: no market quote, player availability, production routing,
deployment eligibility, calibration or PLAY authority is implied.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from math import isfinite
from typing import Mapping, Sequence


def _instant(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("MISSING_EVENT_TIME")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("INVALID_EVENT_TIME") from exc
    if dt.tzinfo is None:
        raise ValueError("NAIVE_EVENT_TIME")
    return dt.astimezone(timezone.utc)


def period_run_distribution(
    prior_games: Sequence[Mapping], *,
    cutoff: str,
    innings: int,
    min_games: int = 20,
) -> dict:
    """Compute prior-only empirical run totals for exactly 3 or 7 innings.

    Each row must provide event and result-availability times, 9+ completed inning run counts,
    and a unique game ID. Every row must predate the target cutoff.
    No rows may be silently dropped, including future or malformed records.
    """
    if innings not in (3, 7):
        raise ValueError("UNSUPPORTED_PERIOD")
    if not isinstance(min_games, int) or isinstance(min_games, bool) or min_games < 1:
        raise ValueError("INVALID_MIN_GAMES")
    target = _instant(cutoff)
    seen = set()
    totals = []
    for game in prior_games:
        gid = game.get("game_id")
        if not isinstance(gid, (str, int)) or isinstance(gid, bool) or not str(gid):
            raise ValueError("MISSING_GAME_ID")
        if str(gid) in seen:
            raise ValueError("DUPLICATE_GAME_ID")
        seen.add(str(gid))
        if _instant(game.get("start_time")) >= target:
            raise ValueError("NON_PRIOR_GAME")
        if "result_available_at" not in game:
            raise ValueError("MISSING_RESULT_AVAILABILITY")
        if _instant(game["result_available_at"]) <= _instant(game["start_time"]):
            raise ValueError("RESULT_AVAILABLE_BEFORE_START")
        if _instant(game["result_available_at"]) >= target:
            raise ValueError("RESULT_NOT_AVAILABLE_AT_CUTOFF")
        scores = game.get("inning_runs")
        if not isinstance(scores, (list, tuple)) or len(scores) < 9:
            raise ValueError("INCOMPLETE_INNINGS")
        if any(not isinstance(x, int) or isinstance(x, bool) or x < 0 for x in scores):
            raise ValueError("INVALID_INNING_RUNS")
        totals.append(sum(scores[:innings]))
    if len(totals) < min_games:
        raise ValueError("INSUFFICIENT_PRIOR_GAMES")
    counts = Counter(totals)
    return {
        "period": f"FIRST_{innings}",
        "games": len(totals),
        "pmf": {str(k): v / len(totals) for k, v in sorted(counts.items())},
        "sample_mean": sum(totals) / len(totals),
        "cutoff": target.isoformat(),
        "validated": False,
        "research_only": True,
        "play_authorized": False,
    }


def price_period_total(distribution: Mapping, *, line: float) -> dict:
    """Research-only O/U/push probabilities; integer lines retain push mass."""
    if not isinstance(line, (float, int)) or isinstance(line, bool) or not isfinite(line) or line < 0:
        raise ValueError("INVALID_LINE")
    pmf = distribution["pmf"]
    over = sum(float(p) for total, p in pmf.items() if int(total) > line)
    under = sum(float(p) for total, p in pmf.items() if int(total) < line)
    push = sum(float(p) for total, p in pmf.items() if int(total) == line)
    return {"over": over, "under": under, "push": push,
            "research_only": True, "play_authorized": False}
