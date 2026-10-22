"""Research-only N-way season futures contract; no betting or promotion authority.

This module does not produce a predictive model. A caller must supply an
independent, market-blind probability distribution with PIT provenance.
Bookmaker N-way normalization is a market benchmark, never Model_P.
A complete caller-declared runner set is structural coverage, NOT external
source admission or proof that a book offered every possible entrant.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import fsum, isfinite
from typing import Mapping


RESEARCH_STATUS = "RESEARCH_ONLY_UNVALIDATED"
SETTLEMENT = "SINGLE_WINNER"  # No dead heat, each-way, group, placement or tie.


class FuturesContractError(ValueError):
    """Named refusal for malformed futures evidence or probability inputs."""


def _identity(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FuturesContractError(f"{name}_REQUIRED")
    return value.strip()


def _aware(value: object, name: str) -> datetime:
    if (not isinstance(value, datetime) or value.tzinfo is None
            or value.utcoffset() is None):
        raise FuturesContractError(f"{name}_TIMEZONE_REQUIRED")
    return value


def _odds(value: object) -> float:
    if (isinstance(value, bool) or not isinstance(value, (float, int))
            or not isfinite(float(value)) or -100 < float(value) < 100):
        raise FuturesContractError("INVALID_FUTURES_AMERICAN_ODDS")
    return float(value)


def _implied(odds: float) -> float:
    return abs(odds) / (abs(odds) + 100) if odds < 0 else 100 / (odds + 100)


def _decimal(odds: float) -> float:
    return 1 + (100 / abs(odds) if odds < 0 else odds / 100)


@dataclass(frozen=True)
class NWayFuturesQuote:
    sport: str
    competition_id: str
    season: str
    contract_id: str
    book: str
    runner_universe_ref: str
    quote_source_ref: str
    expected_runners: tuple[str, ...]
    odds_by_runner: Mapping[str, float]
    source_as_of: datetime
    captured_at: datetime
    settlement: str = SETTLEMENT

    def validate(self, *, now: datetime) -> None:
        for name in ("sport", "competition_id", "season", "contract_id",
                     "book", "runner_universe_ref", "quote_source_ref"):
            _identity(getattr(self, name), name.upper())
        if self.settlement != SETTLEMENT:
            raise FuturesContractError("FUTURES_SETTLEMENT_NOT_SUPPORTED")
        if not isinstance(self.expected_runners, tuple) or len(self.expected_runners) < 2:
            raise FuturesContractError("FUTURES_RUNNER_UNIVERSE_MISSING")
        if any(not isinstance(x, str) or not x.strip() or x != x.strip()
               for x in self.expected_runners):
            raise FuturesContractError("INVALID_FUTURES_RUNNER")
        if len(set(self.expected_runners)) != len(self.expected_runners):
            raise FuturesContractError("DUPLICATE_FUTURES_RUNNER")
        if not isinstance(self.odds_by_runner, Mapping):
            raise FuturesContractError("FUTURES_QUOTES_MISSING")
        if set(self.odds_by_runner) != set(self.expected_runners):
            raise FuturesContractError("INCOMPLETE_OR_MISMATCHED_FUTURES_QUOTES")
        for value in self.odds_by_runner.values():
            _odds(value)
        source = _aware(self.source_as_of, "SOURCE_AS_OF")
        captured = _aware(self.captured_at, "CAPTURED_AT")
        instant = _aware(now, "NOW")
        if source > captured:
            raise FuturesContractError("SOURCE_AFTER_CAPTURE")
        if captured > instant:
            raise FuturesContractError("FUTURE_FUTURES_CAPTURE")

    def market_benchmark(self, *, now: datetime) -> dict[str, float]:
        """Normalize a structurally complete N-way board, market-only."""
        self.validate(now=now)
        raw = {r: _implied(_odds(self.odds_by_runner[r]))
               for r in self.expected_runners}
        denominator = fsum(raw.values())
        if not isfinite(denominator) or denominator <= 0:
            raise FuturesContractError("INVALID_NWAY_OVERROUND")
        return {r: raw[r] / denominator for r in self.expected_runners}


@dataclass(frozen=True)
class IndependentFuturesForecast:
    model_version: str
    model_source_ref: str
    model_cutoff: datetime
    probability_by_runner: Mapping[str, float]

    def validate(self, quote: NWayFuturesQuote) -> None:
        _identity(self.model_version, "MODEL_VERSION")
        _identity(self.model_source_ref, "MODEL_SOURCE_REF")
        cutoff = _aware(self.model_cutoff, "MODEL_CUTOFF")
        if cutoff > quote.source_as_of:
            raise FuturesContractError("MODEL_AFTER_QUOTE_AS_OF")
        if not isinstance(self.probability_by_runner, Mapping) or (
            set(self.probability_by_runner) != set(quote.expected_runners)
        ):
            raise FuturesContractError("FUTURES_MODEL_RUNNERS_MISMATCH")
        values = list(self.probability_by_runner.values())
        if any(isinstance(p, bool) or not isinstance(p, (float, int))
               or not isfinite(float(p)) or not 0 <= float(p) <= 1
               for p in values):
            raise FuturesContractError("INVALID_FUTURES_MODEL_PROBABILITY")
        if abs(fsum(float(p) for p in values) - 1.0) > 1e-8:
            raise FuturesContractError("FUTURES_MODEL_MASS_NOT_ONE")


def screen_futures_research(
    quote: NWayFuturesQuote,
    forecast: IndependentFuturesForecast,
    *,
    now: datetime,
) -> dict[str, object]:
    """Compare model-declared P against a complete quote board, diagnostics only.

    This deliberately NEVER emits PLAY, units, Kelly, official authority or
    a validated claim; independent admission/calibration/OOS verification is
    not implemented here. A book's no-vig reference cannot fill model input.
    """
    benchmark = quote.market_benchmark(now=now)
    forecast.validate(quote)
    rows = []
    for runner in quote.expected_runners:
        odds = _odds(quote.odds_by_runner[runner])
        p = float(forecast.probability_by_runner[runner])
        rows.append({
            "runner": runner,
            "odds_american": odds,
            "model_p_unvalidated": p,
            "market_no_vig_p": benchmark[runner],
            "market_break_even_p": _implied(odds),
            "diagnostic_ev_per_unit": p * _decimal(odds) - 1.0,
            "status": RESEARCH_STATUS,
            "official_authority": False,
            "staking_authority": False,
        })
    return {
        "status": RESEARCH_STATUS,
        "competition_id": quote.competition_id,
        "season": quote.season,
        "contract_id": quote.contract_id,
        "book": quote.book,
        "source_as_of": quote.source_as_of.isoformat(),
        "captured_at": quote.captured_at.isoformat(),
        "model_version": forecast.model_version,
        "runner_universe_ref": quote.runner_universe_ref,
        "quote_source_ref": quote.quote_source_ref,
        "model_source_ref": forecast.model_source_ref,
        "market_overround": fsum(
            _implied(_odds(quote.odds_by_runner[r])) for r in quote.expected_runners
        ) - 1.0,
        "rows": rows,
        "official_authority": False,
        "staking_authority": False,
    }
