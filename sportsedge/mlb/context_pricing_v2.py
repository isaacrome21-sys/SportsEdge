from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import mean
from typing import Iterable, Sequence


@dataclass(frozen=True)
class ParkWeatherSample:
    park: str
    wind_mph: float
    temp_f: float
    dewpoint_f: float
    run_factor: float
    hr_factor: float


@dataclass(frozen=True)
class WeatherLookup:
    status: str
    samples_used: int
    run_factor: float | None
    hr_factor: float | None
    promotion_evidence: bool = False


def park_specific_weather_lookup(samples: Iterable[ParkWeatherSample], *, park: str, wind_mph: float,
                                 temp_f: float, dewpoint_f: float, min_samples: int = 30,
                                 wind_tol: float = 4.0, temp_tol: float = 8.0, dew_tol: float = 10.0) -> WeatherLookup:
    matched = [s for s in samples if s.park == park and abs(s.wind_mph-wind_mph) <= wind_tol
               and abs(s.temp_f-temp_f) <= temp_tol and abs(s.dewpoint_f-dewpoint_f) <= dew_tol]
    if len(matched) < min_samples:
        return WeatherLookup("INSUFFICIENT_EMPIRICAL_WEATHER_SAMPLE", len(matched), None, None)
    return WeatherLookup("OK", len(matched), mean(s.run_factor for s in matched), mean(s.hr_factor for s in matched))


@dataclass(frozen=True)
class CatcherContext:
    framing_runs_per_7000: float
    strike_rate_above_expected: float


def catcher_k_multiplier(ctx: CatcherContext, *, cap: float = 0.02) -> float:
    raw = 0.004 * ctx.strike_rate_above_expected + 0.0002 * ctx.framing_runs_per_7000
    return 1.0 + max(-cap, min(cap, raw))


@dataclass(frozen=True)
class PropQuote:
    book: str
    market: str
    side: str
    line: float
    american_odds: int
    available: bool = True
    max_stake: float | None = None


def american_to_decimal(odds: int) -> float:
    if odds == 0 or (-100 < odds < 100):
        raise ValueError("invalid American odds")
    return 1 + (100/abs(odds) if odds < 0 else odds/100)


def implied_prob(odds: int) -> float:
    return 1.0 / american_to_decimal(odds)


def devig_pair(a: PropQuote, b: PropQuote) -> tuple[float, float]:
    if (a.book, a.market, a.line) != (b.book, b.market, b.line) or {a.side.upper(), b.side.upper()} != {"OVER", "UNDER"}:
        raise ValueError("paired quote identity mismatch")
    qa, qb = implied_prob(a.american_odds), implied_prob(b.american_odds)
    total = qa + qb
    return qa/total, qb/total


def best_executable_quote(quotes: Sequence[PropQuote], *, side: str, min_stake: float = 1.0) -> PropQuote | None:
    candidates = [q for q in quotes if q.side.upper() == side.upper() and q.available and (q.max_stake is None or q.max_stake >= min_stake)]
    if not candidates:
        return None
    return max(candidates, key=lambda q: american_to_decimal(q.american_odds))


def alternate_line_surface(quotes: Sequence[PropQuote], *, book: str, market: str, side: str) -> tuple[PropQuote, ...]:
    rows = [q for q in quotes if q.book == book and q.market == market and q.side.upper() == side.upper() and q.available]
    return tuple(sorted(rows, key=lambda q: q.line))
