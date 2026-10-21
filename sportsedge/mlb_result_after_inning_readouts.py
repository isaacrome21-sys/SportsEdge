"""Research-only cumulative result-after-inning 3-way readout.

This module repackages the already merged F3/F5/F7 moneyline readouts.
Period moneylines treat ties as PUSH; the DraftKings-style three-way
'Result After Nth Inning' treats TIE as its own winning selection.  The
underlying tie mass is preserved EXACTLY -- it must never be discarded,
redistributed, or confused with a baseball final-score tie.

No new distribution or model is built; there are no inputs for prices,
stakes, eligibility, registration, deployment or settlement authority.
The existing M22 canonical blockers remain unchanged.

Innings 2,4,6,8 have no sanctioned cumulative distributions, and refuse
by name rather than extrapolating from neighboring periods.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
import re

from .f5_distribution import F5Distribution, read_f5_probability
from .period_distribution import PeriodDistribution, read_period_probability
from .source_lineage import canonical_json_sha256

READOUT_VERSION = "mlb_result_after_357_three_way_readout_v1"
SUPPORTED_INNINGS = frozenset({3, 5, 7})
MARKET_PATTERN = re.compile(r"^RESULT_AFTER_INNING_([2-8])$")
SELECTIONS = frozenset({"HOME", "TIE", "AWAY"})


class ResultAfterInningError(ValueError):
    """Named fail-closed error for missing or mismatched period evidence."""


@dataclass(frozen=True)
class ResultAfterInningReadout:
    market: str
    innings: int
    selection: str
    probability: float
    push_probability: float
    distribution_sha256: str
    source_readout_sha256: tuple[str, str]
    readout_sha256: str
    readout_version: str = READOUT_VERSION
    status: str = "RESEARCH_ESTIMATE_UNVALIDATED"
    eligible: bool = False
    research_only: bool = True
    market_test: str = "NO_MARKET_TEST"
    play_authority: bool = False
    staking_authority: bool = False


def _read_moneyline_pair(distribution, innings: int):
    """Read both incumbent selections, not a fabricated scoreline prior."""
    if innings == 5:
        if not isinstance(distribution, F5Distribution):
            raise ResultAfterInningError("F5_DISTRIBUTION_REQUIRED")
        try:
            home = read_f5_probability(distribution, market="F5_MONEYLINE",
                                       side="HOME")
            away = read_f5_probability(distribution, market="F5_MONEYLINE",
                                       side="AWAY")
        except ValueError as exc:
            raise ResultAfterInningError(
                "F5_INCUMBENT_DISTRIBUTION_REFUSED") from exc
    else:
        if not isinstance(distribution, PeriodDistribution):
            raise ResultAfterInningError("PERIOD_DISTRIBUTION_REQUIRED")
        if distribution.innings != innings:
            raise ResultAfterInningError("PERIOD_DISTRIBUTION_INNINGS_MISMATCH")
        try:
            home = read_period_probability(
                distribution, market=f"F{innings}_MONEYLINE", side="HOME")
            away = read_period_probability(
                distribution, market=f"F{innings}_MONEYLINE", side="AWAY")
        except ValueError as exc:
            raise ResultAfterInningError(
                "PERIOD_INCUMBENT_DISTRIBUTION_REFUSED") from exc
    probs = (home.probability, away.probability,
             home.push_probability, away.push_probability)
    if any(not isfinite(float(x)) or not 0 <= float(x) <= 1 for x in probs):
        raise ResultAfterInningError("INCUMBENT_MASS_INVALID")
    if home.distribution_sha256 != away.distribution_sha256:
        raise ResultAfterInningError("INCUMBENT_SOURCE_HASH_MISMATCH")
    if abs(home.push_probability - away.push_probability) > 1e-12:
        raise ResultAfterInningError("INCUMBENT_TIE_MASS_MISMATCH")
    if abs(home.probability + away.probability +
           home.push_probability - 1.0) > 1e-12:
        raise ResultAfterInningError("INCUMBENT_THREE_WAY_MASS_NOT_CONSERVED")
    return home, away


def read_result_after_inning(distribution, *, market: str, selection: str
                             ) -> ResultAfterInningReadout:
    """Read HOME/TIE/AWAY over the three *cumulative* period engines.

    The only distribution accepted for a market N is the F{N} scored
    incumbent. Because TIE is a live three-way outcome, push mass on
    the returned readout is exactly zero.
    """
    normalized = str(market or "").upper().strip()
    match = MARKET_PATTERN.fullmatch(normalized)
    if match is None:
        raise ResultAfterInningError("RESULT_AFTER_MARKET_NOT_RECOGNIZED")
    innings = int(match.group(1))
    if innings not in SUPPORTED_INNINGS:
        raise ResultAfterInningError(
            f"NO_CUMULATIVE_DISTRIBUTION_FOR_INNING_{innings}")
    side = str(selection or "").upper().strip()
    if side not in SELECTIONS:
        raise ResultAfterInningError("RESULT_AFTER_SIDE_MUST_BE_HOME_TIE_AWAY")
    home, away = _read_moneyline_pair(distribution, innings)
    probabilities = {
        "HOME": float(home.probability),
        "AWAY": float(away.probability),
        "TIE": float(home.push_probability),
    }
    evidence = {
        "readout_version": READOUT_VERSION,
        "market": normalized,
        "innings": innings,
        "selection": side,
        "underlying_market": f"F{innings}_MONEYLINE",
        "source_distribution_sha256": home.distribution_sha256,
        "source_readout_sha256": [home.readout_sha256, away.readout_sha256],
        "home_probability": probabilities["HOME"],
        "away_probability": probabilities["AWAY"],
        "tie_probability": probabilities["TIE"],
        "selection_probability": probabilities[side],
        "push_probability": 0.0,
    }
    return ResultAfterInningReadout(
        market=normalized, innings=innings, selection=side,
        probability=probabilities[side], push_probability=0.0,
        distribution_sha256=home.distribution_sha256,
        source_readout_sha256=(home.readout_sha256, away.readout_sha256),
        readout_sha256=canonical_json_sha256(evidence))
