"""NHL_TEAM_TOTAL_DIST_V1 — NHL team totals construction (attempt 2).

Implements the construction in
``research/activation_designs_20261027/NHL_TEAM_TOTALS_DESIGN.md``
(PR #2839): per-team regulation goal distributions taken from the
parent attempt-2 construction (``NHL_SIDES_TOTALS_DESIGN.md`` — same
fitted rates, same goaltender adjustment), propagated through the
parent's OT layer when the DraftKings team-total settlement basis
includes overtime, and priced against DK's offered team-total lines.

Design rules carried in code, not in comments alone:

- NO SEPARATE FIT. This module fits nothing. It consumes the parent's
  fitted rates through :class:`ParentGameRates` (regulation goal means
  after the parent's offense/defense combination and goaltender
  adjustment, the parent's dispersion fit, and the parent's OT-layer
  win probability given a regulation tie). When no parent rate
  artifact exists there is nothing to price with — that is the
  design's state on main today, and this module does not paper over
  it with a fit of its own.
- SETTLEMENT BASIS IS RECORDED, NEVER ASSUMED (design, Construction
  bullet 1). ``settlement_basis`` is a required argument with no
  default; anything other than ``"regulation"`` or ``"incl_ot"``
  (including ``None``) refuses as ``SETTLEMENT_BASIS_UNRECORDED``.
  The basis is read from DK's posted market rules at capture time by
  the caller and echoed onto every priced row.
- STRICTLY-PRIOR INPUTS (MoneyPuck admission, PR #2859, section 2.2).
  The parent fit's newest consumed row must be dated strictly before
  the game date; same-day is excluded. Violation refuses as
  ``LOOKAHEAD_RISK`` (the admission's own refusal name, section 7).
- xG VINTAGE (admission section 4.1). Rates carrying more than one
  xG model vintage refuse as ``CROSS_VINTAGE_UNTREATED`` unless the
  consuming preregistration's declared cross-vintage treatment token
  is supplied. The 2025/2026 boundary is the known case
  (``undisclosed_legacy`` vs ``rebuilt_2026_27``).

Distribution law (READING, flagged for the freeze package): the parent
design names "Poisson with a dispersion parameter fit on design data"
without fixing the dispersed family. This module mirrors the repo's
frozen precedent (NFL_TEAM_TOTAL_DIST_V1): a negative-binomial law
with mean ``mu`` and variance ``(c * mu) ** 2``, falling back to
Poisson where variance <= mu. The dispersion ``c`` itself is the
parent fit's value, carried on the rates record — never fitted here.

OT propagation (parent design section 2, bullet 2: OT/SO mass "added
once, from the regulation tie probability"): under the incl-OT basis,
exactly one goal is added, to exactly one team, exactly when
regulation ends tied — the winner's, with the parent's win
probability given a tie. With team goals independent given the rates:

    P(H_incl = k) = pmfH(k) * (1 - pmfA(k))
                  + pmfH(k) * pmfA(k) * (1 - w)
                  + pmfH(k-1) * pmfA(k-1) * w

which conserves mass exactly (the three terms sum over k to
(1 - P_tie) + P_tie * (1 - w) + P_tie * w = 1).

Deterministic: no randomness anywhere in this module.
PAPER / research only. Pricing a game starts no clock and claims no
validation: the family's only validation protocol is the forward
Stage B window in the design (Dec 1, 2026 - Jan 31, 2027), gated on
the parent's Stage A verdict of Nov 30, 2026.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

CONSTRUCTION_ID = "NHL_TEAM_TOTAL_DIST_V1"
MODEL_VERSION = "nhl_team_total_dist_v1"

# Distribution support guard: team goals 0..MAX_GOALS. The grids are
# truncated earlier once the pmf falls below TAIL_EPS past the mode;
# MAX_GOALS is a hard cap, far above any plausible team total.
MAX_GOALS = 40
TAIL_EPS = 1e-13

SETTLEMENT_BASES = ("regulation", "incl_ot")

# Refusal codes. LOOKAHEAD_RISK is the MoneyPuck admission's own code
# (PR #2859, section 7); the others name this family's design rules.
REFUSAL_RATES_INVALID = "RATES_INVALID"
REFUSAL_LOOKAHEAD = "LOOKAHEAD_RISK"
REFUSAL_CROSS_VINTAGE = "CROSS_VINTAGE_UNTREATED"
REFUSAL_BASIS = "SETTLEMENT_BASIS_UNRECORDED"
REFUSAL_LINE_INVALID = "LINE_INVALID"


class TeamTotalRefusal(Exception):
    """Named, fail-closed refusal. ``code`` is the contract."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class ParentGameRates:
    """The parent attempt-2 fit's rates for one game.

    Every field is the parent's output, consumed unchanged (the
    design's "no separate fit" rule). ``away_reg_mean`` /
    ``home_reg_mean`` are regulation goal means AFTER the parent's
    offense/defense combination and goaltender adjustment;
    ``dispersion_cv`` is the parent's fitted dispersion (variance =
    ``(dispersion_cv * mu) ** 2``); ``ot_home_win_prob`` is the
    parent OT layer's probability that the home team wins given a
    regulation tie. Provenance fields attest the fit's inputs:
    ``xg_vintages`` (admission section 4.1 labels),
    ``max_input_gamedate`` (newest MoneyPuck row the fit consumed,
    YYYYMMDD), ``pull_manifest_sha256`` (the pinned pull the fit ran
    on), and ``cross_vintage_treatment`` (the consuming
    preregistration's declared treatment token, or None).
    """

    game_id: str
    game_date: int  # YYYYMMDD
    away_team: str
    home_team: str
    away_reg_mean: float
    home_reg_mean: float
    dispersion_cv: float
    ot_home_win_prob: float
    xg_vintages: Tuple[str, ...]
    max_input_gamedate: int
    pull_manifest_sha256: str
    cross_vintage_treatment: Optional[str] = None


@dataclass(frozen=True)
class PricedTeamTotal:
    """One priced team-total row, with its settlement basis and the
    rates provenance echoed on the row (never assumed, never detached
    from the record that priced it)."""

    construction_id: str
    game_id: str
    game_date: int
    team: str
    side: str  # "away" | "home"
    line: float
    settlement_basis: str
    prob_over: float
    prob_under: float
    prob_push: float
    reg_mean: float
    dispersion_cv: float
    pull_manifest_sha256: str
    xg_vintages: Tuple[str, ...]


def _finite_positive(value: float) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value) and value > 0


def validate_rates(rates: ParentGameRates) -> None:
    """Enforce the design/admission rails on a parent rates record.

    Raises TeamTotalRefusal with a named code; returns None when the
    record is lawful to price from.
    """
    for name, value in (
        ("away_reg_mean", rates.away_reg_mean),
        ("home_reg_mean", rates.home_reg_mean),
        ("dispersion_cv", rates.dispersion_cv),
    ):
        if not _finite_positive(value):
            raise TeamTotalRefusal(
                REFUSAL_RATES_INVALID, f"{name}={value!r} is not finite > 0")
    w = rates.ot_home_win_prob
    if not (isinstance(w, (int, float)) and not isinstance(w, bool)
            and math.isfinite(w) and 0.0 <= w <= 1.0):
        raise TeamTotalRefusal(
            REFUSAL_RATES_INVALID, f"ot_home_win_prob={w!r} not in [0, 1]")
    if not rates.pull_manifest_sha256:
        raise TeamTotalRefusal(
            REFUSAL_RATES_INVALID, "pull_manifest_sha256 is empty")
    if not rates.xg_vintages:
        raise TeamTotalRefusal(
            REFUSAL_RATES_INVALID, "xg_vintages is empty")
    # Strictly-prior (admission section 2.2): the fit may only consume
    # rows dated strictly before the game; same-day is excluded.
    if rates.max_input_gamedate >= rates.game_date:
        raise TeamTotalRefusal(
            REFUSAL_LOOKAHEAD,
            f"newest input row {rates.max_input_gamedate} is not strictly "
            f"before game date {rates.game_date}")
    # Vintage (admission section 4.1): no pooling across xG vintages
    # without a declared treatment in the consuming preregistration.
    if len(set(rates.xg_vintages)) > 1 and not rates.cross_vintage_treatment:
        raise TeamTotalRefusal(
            REFUSAL_CROSS_VINTAGE,
            f"vintages {sorted(set(rates.xg_vintages))} pooled with no "
            "declared cross-vintage treatment")


def _poisson_pmf_grid(mu: float) -> list:
    pmf = [math.exp(-mu)]
    k = 0
    while k < MAX_GOALS:
        nxt = pmf[-1] * mu / (k + 1)
        if k + 1 > mu and nxt < TAIL_EPS:
            break
        pmf.append(nxt)
        k += 1
    return pmf


def nb_pmf_grid(mu: float, c: float) -> list:
    """PMF grid P(X = k), k = 0..len-1, for the construction's law.

    Negative binomial with mean ``mu`` and variance ``(c * mu) ** 2``
    (the repo's frozen NFL team-totals law shape); Poisson where
    variance <= mu.
    """
    if not _finite_positive(mu) or not _finite_positive(c):
        raise TeamTotalRefusal(
            REFUSAL_RATES_INVALID, f"mu={mu!r} c={c!r}")
    var = (c * mu) ** 2
    if var <= mu:
        return _poisson_pmf_grid(mu)
    r = mu * mu / (var - mu)
    p = r / (r + mu)
    pmf = [math.exp(r * math.log(p))]
    k = 0
    while k < MAX_GOALS:
        nxt = pmf[-1] * (k + r) / (k + 1) * (1.0 - p)
        if k + 1 > mu and nxt < TAIL_EPS:
            break
        pmf.append(nxt)
        k += 1
    return pmf


def _incl_ot_pmf(team_pmf: Sequence[float], opp_pmf: Sequence[float],
                 win_prob: float) -> list:
    """Propagate one team's regulation pmf through the OT layer.

    ``win_prob`` is this team's probability of winning given a
    regulation tie. Exactly one goal is added, to the winner, exactly
    when regulation ends tied (see module docstring for the mass
    conservation check).
    """
    n = max(len(team_pmf), len(opp_pmf)) + 1
    out = [0.0] * n
    for k in range(n):
        t_k = team_pmf[k] if k < len(team_pmf) else 0.0
        o_k = opp_pmf[k] if k < len(opp_pmf) else 0.0
        term = t_k * (1.0 - o_k) + t_k * o_k * (1.0 - win_prob)
        if k >= 1:
            t_prev = team_pmf[k - 1] if k - 1 < len(team_pmf) else 0.0
            o_prev = opp_pmf[k - 1] if k - 1 < len(opp_pmf) else 0.0
            term += t_prev * o_prev * win_prob
        out[k] = term
    return out


def team_total_pmf(rates: ParentGameRates, side: str,
                   settlement_basis: Optional[str]) -> list:
    """The team's goal pmf under the row's settlement basis.

    ``settlement_basis`` has no default and is never assumed.
    """
    validate_rates(rates)
    if settlement_basis not in SETTLEMENT_BASES:
        raise TeamTotalRefusal(
            REFUSAL_BASIS,
            f"settlement_basis={settlement_basis!r} not recorded from "
            "DK's posted market rules")
    if side not in ("away", "home"):
        raise TeamTotalRefusal(REFUSAL_RATES_INVALID, f"side={side!r}")
    c = rates.dispersion_cv
    away_pmf = nb_pmf_grid(rates.away_reg_mean, c)
    home_pmf = nb_pmf_grid(rates.home_reg_mean, c)
    if settlement_basis == "regulation":
        return list(away_pmf if side == "away" else home_pmf)
    w = rates.ot_home_win_prob
    if side == "home":
        return _incl_ot_pmf(home_pmf, away_pmf, w)
    return _incl_ot_pmf(away_pmf, home_pmf, 1.0 - w)


def _cdf(pmf: Sequence[float], k: int) -> float:
    if k < 0:
        return 0.0
    if k >= len(pmf):
        return float(sum(pmf))
    return float(sum(pmf[:k + 1]))


def prob_over(pmf: Sequence[float], line: float) -> float:
    """P(goals > line)."""
    return 1.0 - _cdf(pmf, int(math.floor(line)))


def prob_under(pmf: Sequence[float], line: float) -> float:
    """P(goals < line)."""
    return _cdf(pmf, int(math.ceil(line)) - 1)


def prob_push(pmf: Sequence[float], line: float) -> float:
    """P(goals == line); zero unless ``line`` is a whole number."""
    if float(line) != int(line):
        return 0.0
    k = int(line)
    if k < 0 or k >= len(pmf):
        return 0.0
    return float(pmf[k])


def price_team_total(rates: ParentGameRates, side: str, line: float,
                     settlement_basis: Optional[str]) -> PricedTeamTotal:
    """Price one team's total at an offered line under a recorded
    settlement basis. Fail-closed on every design rail."""
    if not (isinstance(line, (int, float)) and not isinstance(line, bool)
            and math.isfinite(line) and line >= 0):
        raise TeamTotalRefusal(REFUSAL_LINE_INVALID, f"line={line!r}")
    pmf = team_total_pmf(rates, side, settlement_basis)
    team = rates.away_team if side == "away" else rates.home_team
    mean = rates.away_reg_mean if side == "away" else rates.home_reg_mean
    return PricedTeamTotal(
        construction_id=CONSTRUCTION_ID,
        game_id=rates.game_id,
        game_date=rates.game_date,
        team=team,
        side=side,
        line=float(line),
        settlement_basis=str(settlement_basis),
        prob_over=prob_over(pmf, line),
        prob_under=prob_under(pmf, line),
        prob_push=prob_push(pmf, line),
        reg_mean=float(mean),
        dispersion_cv=float(rates.dispersion_cv),
        pull_manifest_sha256=rates.pull_manifest_sha256,
        xg_vintages=tuple(rates.xg_vintages),
    )
