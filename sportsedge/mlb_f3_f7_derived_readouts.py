"""Research-only F3/F7 BTTS ladder and winning-margin derived readouts.

Use existing, unchanged first-three/first-seven joint; one distribution
serves both markets. No new model, source, market quote, eligibility,
deployment, runner integration, or DraftKings catalog-availability claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Sequence

from .f5_derived_readouts import (
    margin_band_selection, margin_bands_partition, parse_margin_band,
)
from .mlb_empirical_bayes import JEFFREYS_ALPHA, posterior_settlement_mass
from .period_distribution import PeriodDistribution
from .source_lineage import canonical_json_sha256

VERSION = "mlb_f3_f7_derived_readout_v1_jeffreys"
PERIODS = frozenset({3, 7})
MAX_RESEARCH_RUNG = 7


class F3F7DerivedError(ValueError):
    pass


@dataclass(frozen=True)
class F3F7Readout:
    market: str
    selection: str
    line: int | None
    probability: float
    push_probability: float
    distribution_sha256: str
    readout_sha256: str
    readout_version: str = VERSION
    status: str = "RESEARCH_ESTIMATE_UNVALIDATED"
    eligible: bool = False
    research_only: bool = True
    market_test: str = "NO_MARKET_TEST"
    play_authority: bool = False
    staking_authority: bool = False


def _states(dist: PeriodDistribution, innings: int):
    if not isinstance(dist, PeriodDistribution):
        raise F3F7DerivedError("PERIOD_DISTRIBUTION_REQUIRED")
    if type(innings) is not int or innings not in PERIODS or dist.innings != innings:
        raise F3F7DerivedError("PERIOD_IDENTITY_MISMATCH")
    rows = []
    total = 0.0
    for key, raw in dist.joint_score_pmf.items():
        try:
            a, h = key.split(",")
            away, home, p = int(a), int(h), float(raw)
        except (AttributeError, ValueError, TypeError) as exc:
            raise F3F7DerivedError("INVALID_CUMULATIVE_SCORE_STATE") from exc
        if (key != f"{away},{home}" or min(away, home) < 0 or
                not isfinite(p) or p < 0):
            raise F3F7DerivedError("INVALID_CUMULATIVE_SCORE_STATE")
        total += p
        rows.append((away, home, p))
    if not rows or abs(total - 1.0) > 1e-12:
        raise F3F7DerivedError("CUMULATIVE_MASS_NOT_CONSERVED")
    n = min(dist.away_history_games, dist.home_history_games)
    if isinstance(n, bool) or not isinstance(n, int) or n < 10:
        raise F3F7DerivedError("INSUFFICIENT_CUMULATIVE_HISTORY")
    return rows, float(n)


def _finish(dist, *, market, selection, line, p, extra):
    return F3F7Readout(
        market=market, selection=selection, line=line,
        probability=float(p), push_probability=0.0,
        distribution_sha256=dist.distribution_sha256,
        readout_sha256=canonical_json_sha256({
            "version": VERSION,
            "distribution_sha256": dist.distribution_sha256,
            "market": market, "selection": selection, "line": line,
            "probability": float(p), "push_probability": 0.0,
            "evidence": extra,
        }))


def read_period_derived(dist: PeriodDistribution, *, innings: int,
                        market: str, selection: str, line: Any = None,
                        partition: Sequence[str] | None = None) -> F3F7Readout:
    """Derive only outcomes determined by the cumulative F3/F7 joint.

    Multiway margin requires the ENTIRE bookmaker outcome partition. A
    caller's arbitrary subset cannot be normalized into false certainty.
    Quote identity, source admission and an actual market test are external.
    """
    raw_market = str(market or "").strip().upper()
    btts = f"F{innings}_BOTH_TEAMS_TO_SCORE"
    margin = f"F{innings}_WINNING_MARGIN"
    if raw_market not in {btts, margin}:
        raise F3F7DerivedError("UNRECOGNIZED_F3_F7_DERIVED_MARKET")
    rows, n = _states(dist, innings)
    choice = str(selection or "").strip().upper()
    if raw_market == btts:
        if choice not in {"YES", "NO"}:
            raise F3F7DerivedError("BTTS_YES_NO_REQUIRED")
        if isinstance(line, bool):
            raise F3F7DerivedError("BTTS_INTEGER_RUNG_REQUIRED")
        try:
            val = float(line)
        except (TypeError, ValueError) as exc:
            raise F3F7DerivedError("BTTS_INTEGER_RUNG_REQUIRED") from exc
        if (not isfinite(val) or val != int(val) or
                not 1 <= val <= MAX_RESEARCH_RUNG):
            raise F3F7DerivedError("BTTS_RUNG_OUT_OF_RESEARCH_RANGE")
        rung = int(val)
        yes_mass = sum(p for a, h, p in rows if a >= rung and h >= rung)
        post = posterior_settlement_mass(
            over_mass=yes_mass, under_mass=1.0-yes_mass, push_mass=0,
            effective_n=n, has_push=False)
        p = post["p_over" if choice == "YES" else "p_under"]
        return _finish(dist, market=btts, selection=choice, line=rung,
                       p=p, extra={"raw_yes_mass": yes_mass,
                                    "effective_history_games": n})
    if line is not None:
        raise F3F7DerivedError("MARGIN_MUST_NOT_HAVE_LINE")
    if (not isinstance(partition, Sequence) or
            isinstance(partition, (str, bytes)) or not partition):
        raise F3F7DerivedError("MARGIN_FULL_PARTITION_REQUIRED")
    bands = {}
    for raw in partition:
        try:
            band = parse_margin_band(raw)
            canonical = margin_band_selection(band)
        except ValueError as exc:
            raise F3F7DerivedError("MARGIN_SELECTION_MALFORMED") from exc
        if canonical in bands:
            raise F3F7DerivedError("MARGIN_DUPLICATE_BAND")
        bands[canonical] = band
    if not margin_bands_partition(list(bands.values())):
        raise F3F7DerivedError("MARGIN_INCOMPLETE_PARTITION")
    try:
        choice = margin_band_selection(parse_margin_band(choice))
    except ValueError as exc:
        raise F3F7DerivedError("MARGIN_SELECTION_MALFORMED") from exc
    if choice not in bands:
        raise F3F7DerivedError("MARGIN_SELECTION_NOT_IN_PARTITION")
    raw = {name: sum(p for a, h, p in rows
                     if band.contains(h-a)) for name, band in bands.items()}
    if abs(sum(raw.values()) - 1.0) > 1e-12:
        raise F3F7DerivedError("MARGIN_PARTITION_MASS_NOT_CONSERVED")
    alpha = {name: JEFFREYS_ALPHA + n * value
             for name, value in raw.items()}
    total_alpha = sum(alpha.values())
    return _finish(dist, market=margin, selection=choice, line=None,
                   p=alpha[choice]/total_alpha,
                   extra={"partition": sorted(bands),
                          "raw_cell_mass": raw[choice],
                          "effective_history_games": n})
