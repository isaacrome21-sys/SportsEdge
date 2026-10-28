"""NFL_ENTRY_FORM_V2 — construction module (DESIGN stage; NOT FROZEN).

Implements the construction specified in
``research/nfl_entry_form_v2_20261028/DESIGN.md`` §4 and the pick rule in
``research/nfl_entry_form_v2_20261028/PREREG_DRAFT.md`` §3:

- **Projection core (DESIGN §4.1, mapping spec B).** Per team, from prior
  games only (strictly before the game being priced, REG only):
  offensive EPA/play = (passing EPA + rushing EPA) / (pass attempts +
  sacks suffered + carries); defensive EPA/play allowed = the opponent's
  offensive EPA/play in the same game. Season-window cumulative sums are
  shrunk toward 0 with a 250-play prior; the prior season's final sums
  carry in at weight 0.30. Last-4-games rates are shrunk toward the
  season rate with a 150-play prior, and enter the mapping as a
  form-divergence term (form - season), never as a window replacement.
  Score means are (off - def) x expected plays, with expected plays from
  the team's season pace average; margin and total come from the two
  score means. The per-market OLS mapping (margin ~ EPA margin + form
  divergence; total ~ EPA total + form divergence) is fitted ONCE on
  2020-2025 design data; its coefficients live in
  ``nfl_entry_form_v2_constants`` and are never refit here.
- **Residual-agreement path (DESIGN §4.2).** A per-market OLS on the
  market residual from the frozen context set (margin: form divergence,
  QB EPA delta per side, rest differential; totals: form divergence,
  pace deviation, wind, cold), fitted once on design data. It is a
  SIGN VETO ONLY: it never moves the projection, the line, or the
  probability. A pick requires its sign to agree with the sign of the
  core deviation.
- **Probability (PREREG_DRAFT §3).** ``p = Phi(|d| / sigma_fit)`` on the
  RAW deviation ``d = projection - entry_line``. No anchoring, no
  shrinkage, no cap anywhere between projection and probability (the
  retired construction's defect 2, removed by construction).
- **Pick rule (PREREG_DRAFT §3).** PICK iff sign(adj) == sign(d) AND
  |d| >= 3.0 AND p >= 0.545 AND picked-side DK price >= -165 AND both
  teams have >= 3 prior REG games this season AND both teams' starting-QB
  states are KNOWN from the pricing-time personnel snapshot. Every other
  priced game is a PASS row: recorded, never a pick.
- **No QB edge term exists.** QB/personnel state is an integrity input
  only (DESIGN §3, defect table; the QB-delta hypothesis was falsified
  on design data, SCREEN_RESULTS §3). The QB EPA delta appears solely as
  a feature of the veto path, exactly as DESIGN §4.2 specifies.

STATUS: DESIGN ONLY — NOT FROZEN. This module starts no clock and counts
no rows. Every record it emits carries ``counted = False`` and
``verified_play = False``; counted evaluation is refused by the family
evaluator adapter (``nfl_entry_form_v2_evaluator``) with the named
refusal ``EF_V2_FREEZE_NOT_AUTHORIZED`` until a freeze act pins this
construction under PREREG_DRAFT §7. PAPER / 0u; rows display as LEAN
"unvalidated estimate".
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from sportsedge import nfl_entry_form_v2_constants as C

MODEL_VERSION = C.CONSTRUCTION_ID
MARKETS = ("SPREAD", "TOTAL")

# Named PASS reasons (the first failing gate, in evaluation order).
PASS_ELIGIBILITY = "TEAM_INELIGIBLE"
PASS_STARTER_UNKNOWN = "STARTER_STATE_UNKNOWN"
PASS_AGREEMENT_VETO = "AGREEMENT_VETO"
PASS_DISTANCE = "DISTANCE_GATE"
PASS_PROBABILITY = "PROBABILITY_GATE"
PASS_PRICE_CAP = "PRICE_CAP"


def _module_sha256() -> str:
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError:
        return "UNAVAILABLE"


CONSTRUCTION_SHA256 = _module_sha256()


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TeamWeekLine:
    """One team's offensive line from one played game (nflverse weekly
    team stats shape, DESIGN §4.1 / PINS.json). Defensive EPA allowed is
    derived from the opponent's line of the same game."""

    team: str
    passing_epa: float
    rushing_epa: float
    attempts: float
    sacks_suffered: float
    carries: float

    @property
    def plays(self) -> float:
        return self.attempts + self.sacks_suffered + self.carries

    @property
    def epa_sum(self) -> float:
        return self.passing_epa + self.rushing_epa


@dataclass(frozen=True)
class QBWeekLine:
    """One QB's line from one played game (nflverse weekly player stats
    shape). Used only by the veto path's QB EPA delta (DESIGN §4.2)."""

    player_id: str
    attempts: float
    passing_epa: float
    rushing_epa: float

    @property
    def epa_sum(self) -> float:
        return self.passing_epa + self.rushing_epa


@dataclass(frozen=True)
class GameContext:
    """Everything about a game to be priced that is NOT a market line:
    schedule/context fields for the veto path (DESIGN §4.2) and the
    pricing-time personnel snapshot (PREREG_DRAFT §3). Starter ids may be
    known only via the personnel snapshot; ``*_starter_known`` is the
    integrity flag the pick rule reads — a False flag refuses the pick
    regardless of any id value present."""

    game_id: str
    home_team: str
    away_team: str
    home_rest: float = 0.0
    away_rest: float = 0.0
    roof: str = ""
    wind: float = 0.0
    temp: float = 55.0
    home_starter_id: Optional[str] = None
    away_starter_id: Optional[str] = None
    home_starter_known: bool = False
    away_starter_known: bool = False


@dataclass(frozen=True)
class EntryQuote:
    """The entry snapshot for one market of one game (the lines lane's
    T-1H write in production). ``line`` is in the market's line units:
    home-margin units for SPREAD (nflverse ``spread_line`` convention —
    the market's home-margin estimate; SCREEN_RESULTS sign-convention
    note), total points for TOTAL. Prices are American odds for the two
    sides: (HOME, AWAY) for SPREAD, (OVER, UNDER) for TOTAL."""

    line: float
    price_first: int
    price_second: int
    captured_at: str


# ---------------------------------------------------------------------------
# EPA books (DESIGN §4.1)
# ---------------------------------------------------------------------------

class EPABooks:
    """Season-window shrunk EPA sums with prior-season carry.

    Faithful port of the design screen's RateBook
    (``research/nfl_entry_form_v2_20261028/design_screen.py``), which is
    the design record's reference implementation: rates shrink toward 0
    with a ``PRIOR_PLAYS`` prior; at a season roll the final sums carry
    at ``CARRY_TEAM`` and the in-season game count resets (eligibility
    is an in-season gate, PREREG_DRAFT §3)."""

    def __init__(self) -> None:
        self._agg: Dict[str, dict] = {}

    # -- season lifecycle -------------------------------------------------
    def roll_season(self, prior_final: Optional[Dict[str, dict]] = None) -> None:
        self._agg = {}
        for team, st in (prior_final or {}).items():
            self._agg[team] = {
                "off_epa": st["off_epa"] * C.CARRY_TEAM,
                "plays": st["plays"] * C.CARRY_TEAM,
                "def_epa": st["def_epa"] * C.CARRY_TEAM,
                "def_plays": st["def_plays"] * C.CARRY_TEAM,
                "games": 0,
                "hist": [],
            }

    def final(self) -> Dict[str, dict]:
        return {t: dict(st) for t, st in self._agg.items()}

    # -- state ------------------------------------------------------------
    def _ensure(self, team: str) -> dict:
        if team not in self._agg:
            self._agg[team] = {"off_epa": 0.0, "plays": 0.0, "def_epa": 0.0,
                               "def_plays": 0.0, "games": 0, "hist": []}
        return self._agg[team]

    @staticmethod
    def _rate(epa: float, plays: float) -> float:
        return epa / (plays + C.PRIOR_PLAYS)

    def rates(self, team: str) -> Tuple[float, float, float, int]:
        """(off_rate, def_rate, pace_per_game, prior_reg_games)."""
        st = self._ensure(team)
        pace = st["plays"] / st["games"] if st["games"] else C.PACE_DEFAULT
        return (self._rate(st["off_epa"], st["plays"]),
                self._rate(st["def_epa"], st["def_plays"]),
                pace, st["games"])

    def form_rates(self, team: str) -> Tuple[float, float]:
        """Last-``FORM_WINDOW_GAMES`` rates shrunk toward the season rate
        with a ``FORM_PRIOR_PLAYS`` prior (DESIGN §4.1)."""
        st = self._ensure(team)
        hist = st["hist"][-C.FORM_WINDOW_GAMES:]
        if not hist:
            return self.rates(team)[:2]
        oe = sum(h[0] for h in hist)
        pl = sum(h[1] for h in hist)
        de = sum(h[2] for h in hist)
        dp = sum(h[3] for h in hist)
        so, sd, _, _ = self.rates(team)
        return ((oe + C.FORM_PRIOR_PLAYS * so) / (pl + C.FORM_PRIOR_PLAYS),
                (de + C.FORM_PRIOR_PLAYS * sd) / (dp + C.FORM_PRIOR_PLAYS))

    def add_game(self, home: TeamWeekLine, away: TeamWeekLine) -> None:
        """Ingest one played game. A team's defensive sums are its
        opponent's offensive sums from the same game (DESIGN §4.1)."""
        for team_line, opp_line in ((home, away), (away, home)):
            st = self._ensure(team_line.team)
            st["off_epa"] += team_line.epa_sum
            st["plays"] += team_line.plays
            st["def_epa"] += opp_line.epa_sum
            st["def_plays"] += opp_line.plays
            st["games"] += 1
            st["hist"].append((team_line.epa_sum, team_line.plays,
                               opp_line.epa_sum, opp_line.plays))


class QBBook:
    """Cumulative QB EPA sums for the veto path's QB EPA delta
    (DESIGN §4.2). Shrunk with a ``PRIOR_QB_ATTEMPTS`` prior; prior-season
    sums carry at ``CARRY_QB``. Team sums reset each season, matching the
    design screen's reference implementation."""

    def __init__(self) -> None:
        self._qb: Dict[str, list] = {}
        self._team: Dict[str, list] = {}

    def roll_season(self, prior_qb: Optional[Dict[str, list]] = None) -> None:
        self._qb = {pid: [v[0] * C.CARRY_QB, v[1] * C.CARRY_QB]
                    for pid, v in (prior_qb or {}).items()}
        self._team = {}

    def final_qb(self) -> Dict[str, list]:
        return {pid: list(v) for pid, v in self._qb.items()}

    def add_game(self, team: str, lines: Sequence[QBWeekLine]) -> None:
        for ln in lines:
            if ln.attempts and ln.attempts > 0:
                cur = self._qb.setdefault(ln.player_id, [0.0, 0.0])
                cur[0] += ln.epa_sum
                cur[1] += ln.attempts
                tq = self._team.setdefault(team, [0.0, 0.0])
                tq[0] += ln.epa_sum
                tq[1] += ln.attempts

    def delta(self, team: str, starter_id: Optional[str]) -> float:
        """(starter rate - team rate) x QB_DELTA_ATTEMPT_SCALE. An
        unknown/absent starter contributes 0.0 to the veto feature; the
        pick rule separately refuses any pick whose starter state is not
        KNOWN (PREREG_DRAFT §3), so this fallback can never manufacture
        a pick."""
        if starter_id is None:
            return 0.0
        se, sa = self._qb.get(starter_id, [0.0, 0.0])
        starter_rate = se / (sa + C.PRIOR_QB_ATTEMPTS)
        te, ta = self._team.get(team, [0.0, 0.0])
        team_rate = te / (ta + C.PRIOR_QB_ATTEMPTS)
        return (starter_rate - team_rate) * C.QB_DELTA_ATTEMPT_SCALE


# ---------------------------------------------------------------------------
# Features, projection, veto (DESIGN §4.1 / §4.2)
# ---------------------------------------------------------------------------

def build_features(books: EPABooks, qb_book: QBBook,
                   ctx: GameContext) -> dict:
    """Feature row for one game from the books' CURRENT state (prior
    games only — callers ingest a game only after pricing it). Feature
    names and definitions are the design screen's, which DESIGN §4.1/§4.2
    govern."""
    oh, dh, plh, ngh = books.rates(ctx.home_team)
    oa, da, pla, nga = books.rates(ctx.away_team)
    foh, fdh = books.form_rates(ctx.home_team)
    foa, fda = books.form_rates(ctx.away_team)

    def pts(off: float, dfn: float, plays: float) -> float:
        return (off - dfn) * plays

    exp_h = pts(oh, da, plh)
    exp_a = pts(oa, dh, pla)
    fexp_h = pts(foh, fda, plh)
    fexp_a = pts(foa, fdh, pla)

    outdoor = 1.0 if str(ctx.roof).lower() in ("outdoors", "open") else 0.0
    pace = plh + pla
    return {
        "x_epa_margin": exp_h - exp_a,
        "x_form_margin": (fexp_h - fexp_a) - (exp_h - exp_a),
        "x_qb_h": qb_book.delta(ctx.home_team, ctx.home_starter_id),
        "x_qb_a": -qb_book.delta(ctx.away_team, ctx.away_starter_id),
        "x_rest": float(ctx.home_rest) - float(ctx.away_rest),
        "y_epa_total": exp_h + exp_a,
        "y_form_total": (fexp_h + fexp_a) - (exp_h + exp_a),
        "y_pace": pace,
        "y_pace_dev": pace - C.PACE_LEAGUE_REFERENCE,
        "y_wind": -max(0.0, float(ctx.wind) - C.WIND_THRESHOLD_MPH) * outdoor,
        "y_cold": -max(0.0, C.COLD_THRESHOLD_F - float(ctx.temp)) / C.COLD_SCALE
                  * outdoor,
        "home_prior_games": ngh,
        "away_prior_games": nga,
        "home_starter_known": bool(ctx.home_starter_known),
        "away_starter_known": bool(ctx.away_starter_known),
    }


def project_margin(feat: dict) -> float:
    """Core projection, margin market (home-margin units). OLS spec B,
    coefficients from the constants file; the intercept is the fitted
    home-field constant (DESIGN §4.1). No line enters this function."""
    k = C.CORE_FIT["SPREAD"]
    return (k["intercept"] + k["epa_margin"] * feat["x_epa_margin"]
            + k["form_divergence"] * feat["x_form_margin"])


def project_total(feat: dict) -> float:
    """Core projection, total market. OLS spec B (DESIGN §4.1)."""
    k = C.CORE_FIT["TOTAL"]
    return (k["intercept"] + k["epa_total"] * feat["y_epa_total"]
            + k["form_divergence"] * feat["y_form_total"])


def residual_adjustment(market: str, feat: dict) -> float:
    """The veto path's signed adjustment (DESIGN §4.2). Used ONLY for
    its sign in the pick rule; it is never added to the projection."""
    if market == "SPREAD":
        k = C.RESIDUAL_FIT["SPREAD"]
        return (k["intercept"] + k["form_divergence"] * feat["x_form_margin"]
                + k["qb_home"] * feat["x_qb_h"] + k["qb_away"] * feat["x_qb_a"]
                + k["rest"] * feat["x_rest"])
    if market == "TOTAL":
        k = C.RESIDUAL_FIT["TOTAL"]
        return (k["intercept"] + k["form_divergence"] * feat["y_form_total"]
                + k["pace_deviation"] * feat["y_pace_dev"]
                + k["wind"] * feat["y_wind"] + k["cold"] * feat["y_cold"])
    raise ValueError(f"unknown market {market!r}")


def stated_probability(abs_d: float, market: str) -> float:
    """p = Phi(|d| / sigma_fit) on the raw deviation (PREREG_DRAFT §3).
    Raw and uncapped by construction."""
    return norm_cdf(abs_d / C.SIGMA_FIT[market])


# ---------------------------------------------------------------------------
# Pick rule (PREREG_DRAFT §3)
# ---------------------------------------------------------------------------

def _sides(market: str) -> Tuple[str, str]:
    return ("HOME", "AWAY") if market == "SPREAD" else ("OVER", "UNDER")


def decide_market(market: str, projection: float, adj: float,
                  entry: EntryQuote, feat: dict, *,
                  game_id: str) -> dict:
    """Apply the §3 pick rule for one market of one game and return the
    priced record. Every gate is evaluated and recorded; ``pass_reason``
    names the first failing gate in the fixed order eligibility ->
    starter state -> agreement -> distance -> probability -> price."""
    if market not in MARKETS:
        raise ValueError(f"unknown market {market!r}")
    first, second = _sides(market)
    d = projection - float(entry.line)
    p = stated_probability(abs(d), market)
    side = first if d > 0 else second
    picked_price = entry.price_first if d > 0 else entry.price_second

    gates = {
        "eligibility": (feat["home_prior_games"] >= C.MIN_PRIOR_REG_GAMES
                        and feat["away_prior_games"] >= C.MIN_PRIOR_REG_GAMES),
        "starter_known": (feat["home_starter_known"]
                          and feat["away_starter_known"]),
        "agreement": _sign(adj) == _sign(d) and _sign(d) != 0,
        "distance": abs(d) >= C.DISTANCE_GATE,
        "probability": p >= C.PROBABILITY_GATE,
        "price_cap": picked_price >= C.PRICE_CAP,
    }
    order = (("eligibility", PASS_ELIGIBILITY),
             ("starter_known", PASS_STARTER_UNKNOWN),
             ("agreement", PASS_AGREEMENT_VETO),
             ("distance", PASS_DISTANCE),
             ("probability", PASS_PROBABILITY),
             ("price_cap", PASS_PRICE_CAP))
    pass_reason = None
    for gate_name, reason in order:
        if not gates[gate_name]:
            pass_reason = reason
            break
    is_pick = pass_reason is None
    return {
        "row_id": f"{game_id}:{market}",
        "game_id": game_id,
        "market": market,
        "model_version": MODEL_VERSION,
        "status": C.STATUS,
        "construction_module": __file__,
        "construction_sha256": CONSTRUCTION_SHA256,
        "constants_id": C.CONSTANTS_ID,
        "projection": projection,
        "entry_line": float(entry.line),
        "entry_prices": {first: entry.price_first, second: entry.price_second},
        "entry_captured_at": entry.captured_at,
        "d": d,
        "adj": adj,
        "p_stated": p,
        "sigma_fit": C.SIGMA_FIT[market],
        "features": dict(feat),
        "gates": gates,
        "decision": "PICK" if is_pick else "PASS",
        "pass_reason": pass_reason,
        "selected_side": side if is_pick else "PASS",
        "preferred_side": side,
        "picked_price": picked_price if is_pick else None,
        "counted": False,
        "verified_play": False,
        "display": "LEAN — unvalidated estimate",
        "paper": True,
    }


def price_game(books: EPABooks, qb_book: QBBook, ctx: GameContext,
               quotes: Dict[str, EntryQuote]) -> list:
    """Price both markets of one game from the books' current state.
    ``quotes`` maps market -> EntryQuote (the entry snapshot). Returns
    one record per market present in ``quotes``."""
    feat = build_features(books, qb_book, ctx)
    out = []
    for market in MARKETS:
        if market not in quotes:
            continue
        projection = (project_margin(feat) if market == "SPREAD"
                      else project_total(feat))
        adj = residual_adjustment(market, feat)
        out.append(decide_market(market, projection, adj, quotes[market],
                                 feat, game_id=ctx.game_id))
    return out
