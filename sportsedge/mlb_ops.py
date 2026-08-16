"""Reusable MLB operations primitives for leakage safety, CLV, grading, and health checks.

These helpers are intentionally sportsbook-independent on the model side. Market prices are
accepted only by pricing/CLV helpers after model inference has already occurred.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any, Iterable, Mapping


class MlbOpsError(RuntimeError):
    pass


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        text = str(value or "").strip()
        if not text:
            raise MlbOpsError("TIMESTAMP_MISSING")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            out = datetime.fromisoformat(text)
        except ValueError as exc:
            raise MlbOpsError("TIMESTAMP_INVALID") from exc
    if out.tzinfo is None:
        out = out.replace(tzinfo=timezone.utc)
    return out.astimezone(timezone.utc)


def assert_point_in_time(
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of_field: str = "as_of_utc",
    source_time_field: str = "source_event_time_utc",
    first_pitch_field: str = "first_pitch_utc",
) -> None:
    """Fail when a feature row could contain future/same-game information.

    Contract: source_event_time <= as_of < first_pitch.
    """
    for index, row in enumerate(rows):
        as_of = _dt(row.get(as_of_field))
        source_time = _dt(row.get(source_time_field))
        first_pitch = _dt(row.get(first_pitch_field))
        if source_time > as_of:
            raise MlbOpsError(f"POINT_IN_TIME_SOURCE_AFTER_ASOF:{index}")
        if as_of >= first_pitch:
            raise MlbOpsError(f"POINT_IN_TIME_ASOF_NOT_PREGAME:{index}")


def american_implied_probability(odds: int | float) -> float:
    x = float(odds)
    if x == 0:
        raise MlbOpsError("AMERICAN_ODDS_ZERO")
    if x > 0:
        return 100.0 / (x + 100.0)
    return (-x) / ((-x) + 100.0)


def closing_line_value_bps(*, taken_odds: int | float, closing_odds: int | float) -> float:
    """CLV in probability basis points from the bettor's perspective.

    Positive means the closing market assigned more probability to the selected side than the
    price taken did, i.e. the bettor beat the close. This is a raw single-side measure; callers
    may additionally store a devigged CLV once both sides of the closing market are available.
    """
    taken_p = american_implied_probability(taken_odds)
    close_p = american_implied_probability(closing_odds)
    return (close_p - taken_p) * 10_000.0


def fractional_kelly(
    *,
    model_probability: float,
    american_odds: int | float,
    bankroll: float,
    multiplier: float = 0.25,
    max_fraction: float = 0.05,
) -> float:
    p = float(model_probability)
    if not 0.0 < p < 1.0:
        raise MlbOpsError("MODEL_PROBABILITY_INVALID")
    if bankroll < 0 or multiplier < 0 or max_fraction < 0:
        raise MlbOpsError("KELLY_INPUT_INVALID")
    odds = float(american_odds)
    b = odds / 100.0 if odds > 0 else 100.0 / (-odds)
    q = 1.0 - p
    raw_fraction = max(0.0, (b * p - q) / b)
    fraction = min(raw_fraction * multiplier, max_fraction)
    return bankroll * fraction


@dataclass(frozen=True)
class GradeResult:
    result: str  # WIN, LOSS, PUSH
    actual_value: float | None = None


def grade_count_market(*, side: str, line: float, actual_value: float) -> GradeResult:
    side_u = str(side).upper()
    actual = float(actual_value)
    line_f = float(line)
    if math.isclose(actual, line_f, rel_tol=0.0, abs_tol=1e-12):
        return GradeResult("PUSH", actual)
    if side_u == "OVER":
        return GradeResult("WIN" if actual > line_f else "LOSS", actual)
    if side_u == "UNDER":
        return GradeResult("WIN" if actual < line_f else "LOSS", actual)
    raise MlbOpsError("COUNT_MARKET_SIDE_UNSUPPORTED")


def grade_moneyline(*, selected_team: str, winning_team: str) -> GradeResult:
    return GradeResult("WIN" if str(selected_team) == str(winning_team) else "LOSS")


def grade_nrfi_yrfi(*, market: str, first_inning_runs: int) -> GradeResult:
    m = str(market).upper()
    run_scored = int(first_inning_runs) > 0
    if m == "YRFI":
        return GradeResult("WIN" if run_scored else "LOSS", float(first_inning_runs))
    if m == "NRFI":
        return GradeResult("LOSS" if run_scored else "WIN", float(first_inning_runs))
    raise MlbOpsError("FIRST_INNING_MARKET_UNSUPPORTED")


def deadman_status(*, last_success_utc: Any, now_utc: Any, max_age_minutes: int) -> dict[str, Any]:
    last_success = _dt(last_success_utc)
    now = _dt(now_utc)
    age_minutes = (now - last_success).total_seconds() / 60.0
    if age_minutes < 0:
        raise MlbOpsError("DEADMAN_LAST_SUCCESS_IN_FUTURE")
    ok = age_minutes <= float(max_age_minutes)
    return {
        "ok": ok,
        "age_minutes": age_minutes,
        "max_age_minutes": int(max_age_minutes),
        "reason": None if ok else "DEADMAN_STALE",
    }
