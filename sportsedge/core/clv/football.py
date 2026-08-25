"""Football closing-line-value logging and scoring.

CLV is measured as no-vig probability delta, never raw line movement:
closing_novig_prob(side at the *decision threshold*) - decision_novig_prob(side).

For line markets, a probability observed at a different spread/total threshold is
not comparable. A moved close must therefore carry ``probability_line`` equal to
the original decision line (for example an alternate closing quote at -3 when
the market itself closed -3.5). Legacy rows are accepted only when the market
closing line itself exactly equals the decision line. Incomparable thresholds
fail closed rather than silently reporting zero CLV when juice is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
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
    # Threshold at which ``closing_novig_prob`` was measured. When omitted,
    # ``closing_line`` is the implicit threshold for line markets.
    probability_line: float | None = None


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
    if not isfinite(x) or not 0.0 <= x <= 1.0:
        raise ValueError(f"{field} must be in [0,1]")
    return x


def _line(value: float | None, field: str) -> float | None:
    if value is None:
        return None
    x = float(value)
    if not isfinite(x):
        raise ValueError(f"{field} must be finite")
    return x


def _same_line(left: float, right: float) -> bool:
    return abs(float(left) - float(right)) <= 1e-9


def _assert_comparable_reference(decision: CLVDecision, close: CLVClose) -> None:
    """Require close probability and decision probability to share a threshold."""
    decision_line = _line(decision.line_at_decision, "line_at_decision")
    closing_line = _line(close.closing_line, "closing_line")
    probability_line = _line(close.probability_line, "probability_line")

    if decision_line is None:
        # Moneyline and other line-free markets have no threshold to re-anchor.
        # Supplying one would make the probability's meaning ambiguous.
        if probability_line is not None:
            raise ValueError("CLV_REFERENCE_LINE_MISMATCH")
        return

    if probability_line is not None:
        reference_line = probability_line
    else:
        # Backward-compatible path: the closing probability is understood to be
        # attached to closing_line. It is comparable only if that line did not move.
        if closing_line is None:
            raise ValueError("CLV_REFERENCE_LINE_MISMATCH")
        reference_line = closing_line

    if not _same_line(reference_line, decision_line):
        raise ValueError("CLV_REFERENCE_LINE_MISMATCH")


def score_clv(decisions: Iterable[CLVDecision], closes: Iterable[CLVClose]) -> list[CLVScored]:
    close_index: dict[tuple[str, str, str], CLVClose] = {}
    for close in closes:
        key = (close.game_id, close.market, close.side)
        if key in close_index:
            raise ValueError(f"DUPLICATE_CLOSE:{key}")
        _prob(close.closing_novig_prob, "closing_novig_prob")
        _line(close.closing_line, "closing_line")
        _line(close.probability_line, "probability_line")
        close_index[key] = close

    out: list[CLVScored] = []
    for decision in decisions:
        key = (decision.game_id, decision.market, decision.side)
        close = close_index.get(key)
        if close is None:
            raise ValueError(f"CLOSE_MISSING:{key}")
        _assert_comparable_reference(decision, close)
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
