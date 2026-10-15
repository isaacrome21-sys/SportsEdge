"""Derived read-outs from the shared first-five (F5) joint score state.

The F5 joint distribution (sportsedge.f5_distribution, whose bytes are
pinned in the code-defined model surface) already carries every fact
these DraftKings F5 markets settle on; what was missing is the
read-out layer (backtest matrix M14/M15: "no readout exists"). This
module is that layer, for the three derived families in the verified
F5 set (Oct 13 2026 DraftKings catalog capture, CATALOG_MLB.md,
First-5 section):

* **F5_BOTH_TEAMS_TO_SCORE** -- the Both-Teams-to-Score X+ ladder
  (rungs 1+..7+): P(both clubs score at least N runs through five
  innings), quoted YES/NO per rung.
* **F5_WINNING_MARGIN** -- winning-margin bands over the F5 score
  (e.g. HOME_BY_2, AWAY_BY_3_PLUS, TIE): a multi-outcome market whose
  selections partition the signed-margin space.
* **F5_CORRECT_SCORE** -- exact F5 score cells (AWAY_a_HOME_h) plus
  the book's ANY_OTHER catch-all: a multi-outcome market whose
  selections partition the score space only with the catch-all.

Selection grammars live here, once, and are shared by the quote
binding (sportsedge.mlb_f5_derived_quote_binding) and the settlement
code (sportsedge.mlb_additional_pit_joiner), so a selection means the
same thing at intake, at pricing reachability, and at settlement.

Stabilization follows the same Jeffreys discipline as the F5/period
read-outs: binary read-outs use posterior_settlement_mass; partition
read-outs use the identical per-cell alpha (JEFFREYS_ALPHA +
effective_n * raw) over the market's full partition, so the cells of
one market always sum to one and no sparse cell manufactures
near-certainty. No read-out here pushes: every derived selection is
a plain win/loss cell, so push_probability is identically 0.0.

The pinned F5 module is NOT modified; this module consumes its
F5Distribution objects read-only and carries its own version string.

Research only: nothing here validates, promotes or prices anything.
Eligibility is governed by the deployment registry, consulted by the
binding layer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

from .f5_distribution import F5Distribution
from .mlb_empirical_bayes import JEFFREYS_ALPHA, posterior_settlement_mass
from .source_lineage import canonical_json_sha256

F5_BTTS_MARKET = "F5_BOTH_TEAMS_TO_SCORE"
F5_WINNING_MARGIN_MARKET = "F5_WINNING_MARGIN"
F5_CORRECT_SCORE_MARKET = "F5_CORRECT_SCORE"
F5_DERIVED_MARKETS = frozenset({
    F5_BTTS_MARKET, F5_WINNING_MARGIN_MARKET, F5_CORRECT_SCORE_MARKET})

# The catalog-verified F5 BTTS ladder runs 1+..7+.
BTTS_MIN_RUNG = 1
BTTS_MAX_RUNG = 7

ANY_OTHER = "ANY_OTHER"


def readout_version() -> str:
    return "mlb_f5_derived_readout_v1_jeffreys"


class F5DerivedReadoutError(ValueError):
    pass


@dataclass(frozen=True)
class F5DerivedReadout:
    market: str
    selection: str
    line: float | None
    probability: float
    push_probability: float
    distribution_sha256: str
    readout_sha256: str
    readout_version: str


# ------------------------------------------------------------ grammars

@dataclass(frozen=True)
class MarginBand:
    """One winning-margin band over the signed F5 margin (home - away).

    ``low``/``high`` are inclusive integer bounds; None is an open end.
    TIE is the zero band with team None.
    """
    team: str | None
    low: int | None
    high: int | None

    def contains(self, margin: int) -> bool:
        if self.low is not None and margin < self.low:
            return False
        if self.high is not None and margin > self.high:
            return False
        return True


_MARGIN_RE = re.compile(r"^(HOME|AWAY)_BY_(\d+)(_PLUS)?$")
_SCORE_RE = re.compile(r"^AWAY_(\d+)_HOME_(\d+)$")


def parse_margin_band(selection: Any) -> MarginBand:
    """Parse a canonical winning-margin selection.

    Canonical forms: TIE, {HOME|AWAY}_BY_{k} (exact margin k >= 1),
    {HOME|AWAY}_BY_{k}_PLUS (margin k or more). Anything else raises.
    """
    text = str(selection or "").strip().upper()
    if text in {"TIE", "TIED", "DRAW"}:
        return MarginBand(team=None, low=0, high=0)
    match = _MARGIN_RE.match(text)
    if match is None:
        raise F5DerivedReadoutError(
            f"winning-margin selection must be TIE or "
            f"{{HOME|AWAY}}_BY_{{k}}[_PLUS], got {selection!r}")
    team, k_text, plus = match.group(1), match.group(2), match.group(3)
    k = int(k_text)
    if k < 1:
        raise F5DerivedReadoutError(
            "winning-margin band margin must be >= 1 (a zero margin is TIE)")
    if team == "HOME":
        return MarginBand(team="HOME", low=k, high=None if plus else k)
    return MarginBand(team="AWAY", low=None if plus else -k, high=-k)


def margin_band_selection(band: MarginBand) -> str:
    """The canonical selection string for a parsed band."""
    if band.team is None:
        return "TIE"
    if band.team == "HOME":
        k, open_ended = band.low, band.high is None
    else:
        k, open_ended = -band.high, band.low is None
    return f"{band.team}_BY_{k}" + ("_PLUS" if open_ended else "")


def margin_bands_partition(bands: Sequence[MarginBand]) -> bool:
    """True iff the bands cover every integer margin exactly once.

    The signed-margin space is all integers; a partition needs one
    band open toward -infinity, one open toward +infinity, and
    contiguous non-overlapping coverage in between.
    """
    if not bands:
        return False
    neg_inf, pos_inf = float("-inf"), float("inf")
    intervals = sorted(
        (neg_inf if b.low is None else float(b.low),
         pos_inf if b.high is None else float(b.high))
        for b in bands)
    if intervals[0][0] != neg_inf or intervals[-1][1] != pos_inf:
        return False  # a tail is uncovered
    for (_, prev_high), (low, _) in zip(intervals, intervals[1:]):
        if low != prev_high + 1:
            return False  # gap or overlap between adjacent bands
    return True


def parse_correct_score_selection(selection: Any) -> tuple:
    """Parse a canonical correct-score selection.

    Canonical forms: AWAY_{a}_HOME_{h} (one exact score cell) or
    ANY_OTHER (the book's catch-all for every unlisted score).
    Returns ("CELL", away, home) or ("ANY_OTHER",).
    """
    text = str(selection or "").strip().upper()
    if text in {ANY_OTHER, "OTHER"}:
        return (ANY_OTHER,)
    match = _SCORE_RE.match(text)
    if match is None:
        raise F5DerivedReadoutError(
            f"correct-score selection must be AWAY_{{a}}_HOME_{{h}} or "
            f"ANY_OTHER, got {selection!r}")
    return ("CELL", int(match.group(1)), int(match.group(2)))


def correct_score_selection(parsed: tuple) -> str:
    if parsed[0] == ANY_OTHER:
        return ANY_OTHER
    return f"AWAY_{parsed[1]}_HOME_{parsed[2]}"


def parse_btts_rung(line: Any) -> int:
    """The BTTS ladder rung: an integer in the catalog range 1..7."""
    if isinstance(line, bool) or line is None:
        raise F5DerivedReadoutError("BTTS rung must be an integer line")
    try:
        value = float(line)
    except (TypeError, ValueError) as exc:
        raise F5DerivedReadoutError("BTTS rung must be an integer line") from exc
    if not isfinite(value) or value != int(value):
        raise F5DerivedReadoutError("BTTS rung must be an integer line")
    rung = int(value)
    if rung < BTTS_MIN_RUNG or rung > BTTS_MAX_RUNG:
        raise F5DerivedReadoutError(
            f"BTTS rung {rung} is outside the catalog ladder "
            f"{BTTS_MIN_RUNG}+..{BTTS_MAX_RUNG}+")
    return rung


# ------------------------------------------------------------ readouts

def _states(distribution: F5Distribution):
    if not isinstance(distribution, F5Distribution):
        raise F5DerivedReadoutError("distribution must be F5Distribution")
    total = 0.0
    rows: list[tuple[int, int, float]] = []
    for key, raw_p in distribution.joint_score_pmf.items():
        try:
            away_text, home_text = str(key).split(",", 1)
            away_runs = int(away_text)
            home_runs = int(home_text)
            probability = float(raw_p)
        except (TypeError, ValueError) as exc:
            raise F5DerivedReadoutError("invalid F5 joint score state") from exc
        if away_runs < 0 or home_runs < 0 or not isfinite(probability) or probability < 0:
            raise F5DerivedReadoutError("invalid F5 joint score state")
        total += probability
        rows.append((away_runs, home_runs, probability))
    if abs(total - 1.0) > 1e-12:
        raise F5DerivedReadoutError("F5 joint score PMF does not conserve probability")
    return tuple(rows)


def _effective_n(distribution: F5Distribution) -> float:
    return float(min(distribution.away_history_games,
                     distribution.home_history_games))


def _jeffreys_partition(raw: Mapping[str, float], effective_n: float) -> dict[str, float]:
    """Multinomial Jeffreys posterior over a full partition's cells --
    the same per-cell alpha the settlement-mass posterior uses
    (JEFFREYS_ALPHA + effective_n * raw), normalized over the cells."""
    if not raw:
        raise F5DerivedReadoutError("partition must carry at least one cell")
    total_raw = sum(raw.values())
    if abs(total_raw - 1.0) > 1e-9:
        raise F5DerivedReadoutError("partition cells do not conserve probability")
    alpha = {name: JEFFREYS_ALPHA + effective_n * float(mass)
             for name, mass in raw.items()}
    total_alpha = sum(alpha.values())
    return {name: value / total_alpha for name, value in alpha.items()}


def _readout(distribution: F5Distribution, *, market: str, selection: str,
             line: float | None, probability: float,
             payload_extra: Mapping[str, Any]) -> F5DerivedReadout:
    version = readout_version()
    payload: dict[str, Any] = {
        "version": version,
        "distribution_sha256": distribution.distribution_sha256,
        "market": market,
        "selection": selection,
        "line": line,
        "probability": float(probability),
        "push_probability": 0.0,
    }
    payload.update(payload_extra)
    return F5DerivedReadout(
        market=market,
        selection=selection,
        line=line,
        probability=float(probability),
        push_probability=0.0,
        distribution_sha256=distribution.distribution_sha256,
        readout_sha256=canonical_json_sha256(payload),
        readout_version=version,
    )


def read_f5_btts_probability(
    distribution: F5Distribution,
    *,
    line: Any,
    side: str,
) -> F5DerivedReadout:
    """P(both clubs score at least ``line`` runs through five innings),
    read for the YES or NO side of one ladder rung."""
    rung = parse_btts_rung(line)
    side = str(side or "").upper()
    if side not in {"YES", "NO"}:
        raise F5DerivedReadoutError(f"BTTS side must be YES or NO, got {side!r}")
    rows = _states(distribution)
    yes_mass = sum(p for away, home, p in rows if away >= rung and home >= rung)
    posterior = posterior_settlement_mass(
        over_mass=float(yes_mass),
        under_mass=float(1.0 - yes_mass),
        push_mass=0.0,
        effective_n=_effective_n(distribution),
        has_push=False,
    )
    probability = posterior["p_over"] if side == "YES" else posterior["p_under"]
    return _readout(
        distribution, market=F5_BTTS_MARKET, selection=side,
        line=float(rung), probability=float(probability),
        payload_extra={
            "rung": rung,
            "raw_yes_mass": float(yes_mass),
            "posterior_prior": posterior["prior"],
            "effective_history_games": _effective_n(distribution),
        })


def read_f5_winning_margin_probability(
    distribution: F5Distribution,
    *,
    partition: Sequence[str],
    selection: str,
) -> F5DerivedReadout:
    """Probability of one winning-margin band, stabilized over the
    market's full quoted partition (which must partition the signed
    margin space -- verified mechanically, never assumed)."""
    bands: dict[str, MarginBand] = {}
    for raw_selection in partition:
        band = parse_margin_band(raw_selection)
        canonical = margin_band_selection(band)
        if canonical in bands:
            raise F5DerivedReadoutError(
                f"duplicate winning-margin selection in partition: {canonical}")
        bands[canonical] = band
    if not margin_bands_partition(list(bands.values())):
        raise F5DerivedReadoutError(
            "winning-margin selections do not partition the margin space")
    selected = margin_band_selection(parse_margin_band(selection))
    if selected not in bands:
        raise F5DerivedReadoutError(
            f"winning-margin selection {selected} is not in the quoted partition")
    rows = _states(distribution)
    raw = {
        name: sum(p for away, home, p in rows if band.contains(home - away))
        for name, band in bands.items()
    }
    posterior = _jeffreys_partition(raw, _effective_n(distribution))
    return _readout(
        distribution, market=F5_WINNING_MARGIN_MARKET, selection=selected,
        line=None, probability=posterior[selected],
        payload_extra={
            "partition": sorted(bands),
            "raw_cell_mass": raw[selected],
            "effective_history_games": _effective_n(distribution),
        })


def read_f5_correct_score_probability(
    distribution: F5Distribution,
    *,
    partition: Sequence[str],
    selection: str,
) -> F5DerivedReadout:
    """Probability of one correct-score selection, stabilized over the
    quoted partition (exact cells + the ANY_OTHER catch-all, which
    must be present -- without it the quoted cells cannot partition
    the score space)."""
    cells: dict[str, tuple] = {}
    for raw_selection in partition:
        parsed = parse_correct_score_selection(raw_selection)
        canonical = correct_score_selection(parsed)
        if canonical in cells:
            raise F5DerivedReadoutError(
                f"duplicate correct-score selection in partition: {canonical}")
        cells[canonical] = parsed
    if ANY_OTHER not in cells:
        raise F5DerivedReadoutError(
            "correct-score partition requires the ANY_OTHER catch-all: "
            "quoted exact cells alone cannot partition the score space")
    selected = correct_score_selection(parse_correct_score_selection(selection))
    if selected not in cells:
        raise F5DerivedReadoutError(
            f"correct-score selection {selected} is not in the quoted partition")
    rows = _states(distribution)
    raw: dict[str, float] = {}
    listed = 0.0
    for name, parsed in cells.items():
        if parsed[0] == ANY_OTHER:
            continue
        mass = sum(p for away, home, p in rows
                   if away == parsed[1] and home == parsed[2])
        raw[name] = mass
        listed += mass
    raw[ANY_OTHER] = max(0.0, 1.0 - listed)
    posterior = _jeffreys_partition(raw, _effective_n(distribution))
    return _readout(
        distribution, market=F5_CORRECT_SCORE_MARKET, selection=selected,
        line=None, probability=posterior[selected],
        payload_extra={
            "partition": sorted(cells),
            "raw_cell_mass": raw[selected],
            "effective_history_games": _effective_n(distribution),
        })
