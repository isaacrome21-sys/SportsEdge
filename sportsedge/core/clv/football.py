"""Football closing-line-value logging and scoring.

CLV is measured as no-vig probability delta, never raw line movement:
closing_novig_prob(side) - decision_novig_prob(side).
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean, stdev
from typing import Iterable


@dataclass(frozen=True)
class CLVDecision:
    decision_ts: str
    game_id: str
    sport: str
    market: str
    side: str
    book: str
    line_at_decision: float | None
    price_at_decision: float
    model_prob: float
    novig_prob: float
    ev: float
    kelly_frac: float
    stake_units: float
    gate_result: str


@dataclass(frozen=True)
class CLVClose:
    game_id: str
    market: str
    side: str
    closing_line: float | None
    closing_price: float
    closing_novig_prob: float


@dataclass(frozen=True)
class CLVScored:
    decision: CLVDecision
    close: CLVClose
    clv: float


@dataclass(frozen=True)
class CLVSummary:
    n: int
    mean_clv: float
    beat_close_rate: float
    t_stat: float


def _prob(value: float, field: str) -> float:
    x = float(value)
    if not 0.0 <= x <= 1.0:
        raise ValueError(f"{field} must be in [0,1]")
    return x


def score_clv(decisions: Iterable[CLVDecision], closes: Iterable[CLVClose]) -> list[CLVScored]:
    close_index: dict[tuple[str, str, str], CLVClose] = {}
    for close in closes:
        key = (close.game_id, close.market, close.side)
        if key in close_index:
            raise ValueError(f"DUPLICATE_CLOSE:{key}")
        _prob(close.closing_novig_prob, "closing_novig_prob")
        close_index[key] = close

    out: list[CLVScored] = []
    for decision in decisions:
        key = (decision.game_id, decision.market, decision.side)
        close = close_index.get(key)
        if close is None:
            raise ValueError(f"CLOSE_MISSING:{key}")
        decision_p = _prob(decision.novig_prob, "novig_prob")
        close_p = _prob(close.closing_novig_prob, "closing_novig_prob")
        out.append(CLVScored(decision, close, close_p - decision_p))
    return out


def _gate_bucket(gate_result: str) -> str:
    return "OFFICIAL" if gate_result == "OFFICIAL" else "REJECTED"


def summarize_clv(scored: Iterable[CLVScored]) -> dict[tuple[str, str, str], CLVSummary]:
    groups: dict[tuple[str, str, str], list[float]] = {}
    for row in scored:
        key = (row.decision.sport, row.decision.market, _gate_bucket(row.decision.gate_result))
        groups.setdefault(key, []).append(float(row.clv))

    report: dict[tuple[str, str, str], CLVSummary] = {}
    for key, values in groups.items():
        n = len(values)
        mu = mean(values)
        beat = sum(v > 0.0 for v in values) / n
        if n < 2:
            t_stat = 0.0
        else:
            sd = stdev(values)
            t_stat = 0.0 if sd == 0.0 else mu / (sd / sqrt(n))
        report[key] = CLVSummary(n=n, mean_clv=mu, beat_close_rate=beat, t_stat=t_stat)
    return report


def replay_clv_week(decisions: Iterable[CLVDecision], closes: Iterable[CLVClose]) -> dict[tuple[str, str, str], CLVSummary]:
    """End-to-end replay entry point for one archived historical week."""
    return summarize_clv(score_clv(decisions, closes))
