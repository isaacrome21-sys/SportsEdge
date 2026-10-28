"""NHL_ATTEMPT2_V1 — NHL attempt-2 sides / totals construction.

Implements the merged design draft exactly as written
(research/activation_designs_20261027/NHL_SIDES_TOTALS_DESIGN.md):

1. Team offensive/defensive goal rates from MoneyPuck expected goals,
   strictly prior games only, exponentially weighted (half-life in
   team games), shrunk toward league rates by games played. A
   goaltender adjustment comes from the confirmed starter's
   strictly-prior save performance vs shot quality faced; an
   unconfirmed starter prices off the team's weighted starter/backup
   blend and the price is flagged degraded.
2. Regulation-first simulation: regulation goal distributions per team
   (negative binomial; Poisson at dispersion phi = 1), then the OT/SO
   layer added ONCE from the regulation tie probability — the exact
   inverse of attempt 1's double-count, which stays retired.
3. Outputs from the one simulation: moneyline (incl. OT/SO), puck line
   -1.5/+1.5, game totals (regulation + OT goal), and regulation-only
   markets (3-way moneyline, regulation totals).

Enforcement carried in code, per the MoneyPuck admission record
(research/nhl_moneypuck_admission_20261028/ADMISSION_RECORD.md):
- STRICTLY-PRIOR: a feature for a game on date D is built only from
  rows with gameDate strictly before D (admission section 2.2). Same-day
  rows never contribute.
- XG VINTAGE: rows carry the xG model vintage of their season
  (admission section 4.1). A fit whose used rows span the 2025/2026
  vintage boundary refuses (XG_VINTAGE_POOLING_REFUSED) unless the one
  treatment the design + admission declare is in force — restriction
  to the single rebuilt 2026-27 vintage, with legacy rows excluded and
  counted, never pooled. Any other treatment name refuses
  (XG_VINTAGE_TREATMENT_UNDECLARED).
- NOT FROZEN: the frozen-constants pricing path refuses
  (NHL_ATTEMPT2_NOT_FROZEN) while the design's freeze-owed values
  (half-life, shrinkage weights) are unpinned. Build-stage pricing
  takes an explicit Params object and stamps every output
  counted=False / frozen=False / validation_credit=False.

Stage A (the locked home-ice v2 pre-lock) is a separate construction
and is not touched, consumed, or re-scored here. Stage B market
validation is a forward protocol (Dec 1, 2026 - Jan 31, 2027) whose
window has not opened; see research/nhl_attempt2_build_20261028/
SCREEN_RECORD.md for the screen adjudication of record.

Stdlib only.
"""

from __future__ import annotations

import csv
import io
import math
import zipfile
from dataclasses import dataclass

from sportsedge import nhl_attempt2_constants as C


class Attempt2Refusal(Exception):
    """Named refusal, in the admission record's refusal style."""

    def __init__(self, code, **detail):
        super().__init__(code)
        self.code = code
        self.detail = detail


# --------------------------------------------------------------------------
# Rows
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class TeamGameRow:
    team: str
    opponent: str
    season: int
    gamedate: int          # YYYYMMDD
    home_or_away: str      # 'HOME' / 'AWAY' as served by the source
    xgoals_for: float
    xgoals_against: float
    goals_for: float
    goals_against: float
    playoff_game: bool = False

    @property
    def vintage(self):
        return vintage_for_season(self.season)


@dataclass(frozen=True)
class GoalieGameRow:
    player_id: str
    name: str
    team: str
    season: int
    gamedate: int          # YYYYMMDD
    xgoals_faced: float    # MoneyPuck goalies surface: 'xGoals' column
    goals_allowed: float   # 'goals' column
    icetime_seconds: float = 0.0

    @property
    def vintage(self):
        return vintage_for_season(self.season)


def vintage_for_season(season):
    """Admission section 4.1: rebuilt for 2026-27; legacy undisclosed."""
    return (C.VINTAGE_REBUILT_2026_27 if int(season) >= C.VINTAGE_BOUNDARY_SEASON
            else C.VINTAGE_UNDISCLOSED_LEGACY)


def _parse_gamedate(value):
    text = str(value).strip()
    if len(text) != 8 or not text.isdigit():
        raise Attempt2Refusal("SCHEMA_INVALID", bad_gameDate=value)
    return int(text)


def team_rows_from_dicts(dicts, situation=C.SITUATION_BASIS):
    rows = []
    for d in dicts:
        if str(d.get("situation")) != situation:
            continue
        try:
            rows.append(TeamGameRow(
                team=str(d["playerTeam"]),
                opponent=str(d["opposingTeam"]),
                season=int(d["season"]),
                gamedate=_parse_gamedate(d["gameDate"]),
                home_or_away=str(d.get("home_or_away", "")),
                xgoals_for=float(d["xGoalsFor"]),
                xgoals_against=float(d["xGoalsAgainst"]),
                goals_for=float(d.get("goalsFor") or 0),
                goals_against=float(d.get("goalsAgainst") or 0),
                playoff_game=str(d.get("playoffGame")) not in ("0", "0.0", ""),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            raise Attempt2Refusal("SCHEMA_INVALID", error=str(exc))
    return rows


def load_team_rows(path, seasons=None, situation=C.SITUATION_BASIS):
    """Stream the game-by-game team surface (all_teams.csv shape)."""
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for d in csv.DictReader(fh):
            if seasons is not None and int(d["season"]) not in seasons:
                continue
            out.extend(team_rows_from_dicts([d], situation=situation))
    return out


def goalie_rows_from_dicts(dicts, situation=C.SITUATION_BASIS):
    rows = []
    for d in dicts:
        if str(d.get("situation")) != situation:
            continue
        try:
            rows.append(GoalieGameRow(
                player_id=str(d["playerId"]),
                name=str(d.get("name", "")),
                team=str(d["playerTeam"]),
                season=int(d["season"]),
                gamedate=_parse_gamedate(d["gameDate"]),
                xgoals_faced=float(d["xGoals"]),
                goals_allowed=float(d["goals"]),
                icetime_seconds=float(d.get("icetime") or 0),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            raise Attempt2Refusal("SCHEMA_INVALID", error=str(exc))
    return rows


def load_goalie_rows(path, seasons=None, situation=C.SITUATION_BASIS):
    """Read a season goalies zip (one CSV member, per the admission)."""
    zf = zipfile.ZipFile(path)
    names = [n for n in zf.namelist() if n.endswith(".csv")]
    if len(names) != 1:
        raise Attempt2Refusal("SCHEMA_INVALID", zip_members=zf.namelist())
    out = []
    with zf.open(names[0]) as fh:
        for d in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8")):
            if seasons is not None and int(d["season"]) not in seasons:
                continue
            out.extend(goalie_rows_from_dicts([d], situation=situation))
    return out


# --------------------------------------------------------------------------
# Vintage scope (admission section 4.1, enforced)
# --------------------------------------------------------------------------

def apply_vintage_scope(rows, treatment):
    """Return (kept_rows, excluded_count) under the vintage rule.

    Pooling used rows across the 2025/2026 xG vintage boundary is
    refused unless the declared treatment is in force; the declared
    treatment restricts the fit to the rebuilt 2026-27 vintage and
    counts every excluded legacy row. An unrecognized treatment name
    refuses: no other cross-vintage treatment is declared anywhere in
    the design or the admission.
    """
    vintages = {r.vintage for r in rows}
    if len(vintages) <= 1:
        return list(rows), 0
    if treatment is None:
        raise Attempt2Refusal(
            "XG_VINTAGE_POOLING_REFUSED",
            vintages=sorted(vintages),
            rule="admission section 4.1: xG must not be pooled across "
                 "the 2025/2026 boundary without a declared treatment")
    if treatment != C.DECLARED_CROSS_VINTAGE_TREATMENT:
        raise Attempt2Refusal(
            "XG_VINTAGE_TREATMENT_UNDECLARED", treatment=treatment,
            declared=C.DECLARED_CROSS_VINTAGE_TREATMENT)
    kept = [r for r in rows if r.vintage == C.VINTAGE_REBUILT_2026_27]
    return kept, len(rows) - len(kept)


# --------------------------------------------------------------------------
# Parameters
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Params:
    half_life_games: float
    shrinkage_prior_games: float
    goalie_shrinkage_games: float
    phi: float = C.DISPERSION_PHI
    ot_home_win_share: float = C.OT_HOME_WIN_SHARE
    ot_decision_share: float = C.OT_DECISION_SHARE
    treatment: str | None = C.DECLARED_CROSS_VINTAGE_TREATMENT

    def __post_init__(self):
        if self.half_life_games is None or self.half_life_games <= 0:
            raise ValueError("half_life_games must be a positive number")
        if self.shrinkage_prior_games is None or self.shrinkage_prior_games < 0:
            raise ValueError("shrinkage_prior_games must be >= 0")
        if self.goalie_shrinkage_games is None or self.goalie_shrinkage_games < 0:
            raise ValueError("goalie_shrinkage_games must be >= 0")
        if self.phi < 1.0:
            raise ValueError("phi (dispersion, Var = phi * mean) must be >= 1")
        if not (0.0 <= self.ot_home_win_share <= 1.0):
            raise ValueError("ot_home_win_share must be in [0, 1]")
        if not (0.0 <= self.ot_decision_share <= 1.0):
            raise ValueError("ot_decision_share must be in [0, 1]")


def params_from_constants():
    """The frozen-constants pricing path.

    Refuses NHL_ATTEMPT2_NOT_FROZEN while any value the design fixes
    only at freeze (half-life, shrinkage weights) is unpinned in the
    constants file. No caller bypass: build-stage work passes an
    explicit Params and its outputs are stamped NOT FROZEN.
    """
    missing = [name for name in ("HALF_LIFE_GAMES", "SHRINKAGE_PRIOR_GAMES",
                                 "GOALIE_SHRINKAGE_GAMES")
               if getattr(C, name) is None]
    if missing:
        raise Attempt2Refusal("NHL_ATTEMPT2_NOT_FROZEN", missing=missing,
                              rule="design section 1: half-life fixed at "
                                   "freeze; shrinkage weights unpinned "
                                   "in the draft")
    return Params(half_life_games=C.HALF_LIFE_GAMES,
                  shrinkage_prior_games=C.SHRINKAGE_PRIOR_GAMES,
                  goalie_shrinkage_games=C.GOALIE_SHRINKAGE_GAMES)


# --------------------------------------------------------------------------
# Rates (design section 1)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class TeamRate:
    team: str
    off_rate: float        # xG for per game, weighted + shrunk
    def_rate: float        # xG against per game, weighted + shrunk
    games: int
    weight_sum: float


@dataclass(frozen=True)
class RateBook:
    league_rate: float
    league_off: float
    league_def: float
    rates: dict            # team -> TeamRate
    target_date: int
    rows_used: int
    vintage_excluded_rows: int


def _weights_by_recency(games_sorted, half_life_games):
    """Exponential weights over team games, newest game weight 1."""
    n = len(games_sorted)
    return [0.5 ** ((n - 1 - i) / half_life_games) for i in range(n)]


def build_rate_book(team_rows, target_date, params):
    """Strictly-prior, vintage-scoped, exponentially weighted rates.

    Only rows with gamedate strictly before target_date are used
    (admission section 2.2); the vintage scope is applied to that
    strictly-prior pool before any rate is computed.
    """
    prior = [r for r in team_rows if r.gamedate < target_date]
    if not prior:
        raise Attempt2Refusal("LOOKAHEAD_RISK", target_date=target_date,
                              reason="no strictly-prior rows; the filter "
                                     "cannot speak to this date")
    scoped, excluded = apply_vintage_scope(prior, params.treatment)
    by_team = {}
    for r in scoped:
        by_team.setdefault(r.team, []).append(r)
    weighted = []          # (row, weight) across the whole pool
    team_weighted = {}
    for team, games in by_team.items():
        games_sorted = sorted(games, key=lambda r: r.gamedate)
        ws = _weights_by_recency(games_sorted, params.half_life_games)
        team_weighted[team] = list(zip(games_sorted, ws))
        weighted.extend(team_weighted[team])
    total_w = sum(w for _, w in weighted)
    league_off = sum(w * r.xgoals_for for r, w in weighted) / total_w
    league_def = sum(w * r.xgoals_against for r, w in weighted) / total_w
    league_rate = (league_off + league_def) / 2.0
    k = params.shrinkage_prior_games
    rates = {}
    for team, games_ws in team_weighted.items():
        wsum = sum(w for _, w in games_ws)
        off = (sum(w * r.xgoals_for for r, w in games_ws) + k * league_off) \
            / (wsum + k)
        def_ = (sum(w * r.xgoals_against for r, w in games_ws)
                + k * league_def) / (wsum + k)
        rates[team] = TeamRate(team=team, off_rate=off, def_rate=def_,
                               games=len(games_ws), weight_sum=wsum)
    return RateBook(league_rate=league_rate, league_off=league_off,
                    league_def=league_def, rates=rates,
                    target_date=target_date, rows_used=len(scoped),
                    vintage_excluded_rows=excluded)


# --------------------------------------------------------------------------
# Goaltender adjustment (design section 1)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class GoalieAdjustment:
    team: str
    delta_per_game: float  # goals saved above xG per game, shrunk; this
                           # amount is SUBTRACTED from the opponent mean
    confirmed: bool
    degraded: bool
    games: int
    goalies_considered: int
    vintage_excluded_rows: int


def goalie_adjustment(goalie_rows, team, target_date, params,
                      starter_player_id=None):
    prior = [r for r in goalie_rows
             if r.team == team and r.gamedate < target_date]
    if not prior:
        raise Attempt2Refusal("LOOKAHEAD_RISK", team=team,
                              target_date=target_date,
                              reason="no strictly-prior goalie rows")
    scoped, excluded = apply_vintage_scope(prior, params.treatment)
    by_goalie = {}
    for r in scoped:
        by_goalie.setdefault(r.player_id, []).append(r)

    def per_game(rows):
        games = len(rows)
        return (sum(r.xgoals_faced for r in rows)
                - sum(r.goals_allowed for r in rows)) / games, games

    k = params.goalie_shrinkage_games
    if starter_player_id is not None:
        rows = by_goalie.get(str(starter_player_id))
        if not rows:
            raise Attempt2Refusal(
                "GOALIE_STARTER_NO_PRIOR", team=team,
                starter_player_id=str(starter_player_id),
                reason="confirmed starter has no strictly-prior rows; "
                       "a delta cannot be fabricated")
        delta_pg, games = per_game(rows)
        delta = delta_pg * games / (games + k) if (games + k) > 0 else 0.0
        return GoalieAdjustment(team=team, delta_per_game=delta,
                                confirmed=True, degraded=False, games=games,
                                goalies_considered=1,
                                vintage_excluded_rows=excluded)
    # Unconfirmed: weighted starter/backup blend (weights = games),
    # flagged degraded — starter identity is not availability.
    total_games = sum(len(v) for v in by_goalie.values())
    pooled_pg = (sum(r.xgoals_faced for v in by_goalie.values() for r in v)
                 - sum(r.goals_allowed for v in by_goalie.values()
                       for r in v)) / total_games
    delta = pooled_pg * total_games / (total_games + k) \
        if (total_games + k) > 0 else 0.0
    return GoalieAdjustment(team=team, delta_per_game=delta,
                            confirmed=False, degraded=True,
                            games=total_games,
                            goalies_considered=len(by_goalie),
                            vintage_excluded_rows=excluded)


# --------------------------------------------------------------------------
# Regulation-first simulation (design section 2)
# --------------------------------------------------------------------------

def goal_pmf(mean, phi):
    """Goal distribution on 0..MAX_GOALS, tail folded into the last cell.

    Negative binomial with Var = phi * mean; phi == 1 is exact Poisson.
    """
    if mean <= 0:
        raise ValueError("mean must be positive")
    raw = []
    if phi <= 1.0:
        log_mean = math.log(mean)
        for k in range(C.MAX_GOALS + 1):
            raw.append(math.exp(-mean + k * log_mean - math.lgamma(k + 1)))
    else:
        r = mean / (phi - 1.0)
        p = r / (r + mean)
        log_p = math.log(p)
        log_q = math.log(1.0 - p)
        lg_r = math.lgamma(r)
        for k in range(C.MAX_GOALS + 1):
            raw.append(math.exp(math.lgamma(k + r) - lg_r
                                - math.lgamma(k + 1)
                                + r * log_p + k * log_q))
    total = sum(raw)
    raw[-1] += 1.0 - total     # fold the tail; mass is preserved exactly
    return raw


@dataclass(frozen=True)
class SimOutputs:
    mu_home: float
    mu_away: float
    p_home_reg_win: float
    p_reg_tie: float
    p_away_reg_win: float
    p_home_ml: float           # incl. OT/SO layer
    p_away_ml: float           # incl. OT/SO layer
    p_home_puck_line_minus15: float
    p_away_puck_line_plus15: float
    reg_total_pmf: tuple       # regulation totals 0..2*MAX_GOALS
    final_total_pmf: tuple     # incl. the single OT goal, when it happens;
                               # runs to 2*MAX_GOALS + 1

    def totals(self, line, regulation_only=False):
        """(over, under, push) probabilities at an offered total line."""
        pmf = self.reg_total_pmf if regulation_only else self.final_total_pmf
        over = sum(p for k, p in enumerate(pmf) if k > line)
        under = sum(p for k, p in enumerate(pmf) if k < line)
        push = pmf[int(line)] if float(line).is_integer() \
            and 0 <= int(line) < len(pmf) else 0.0
        return over, under, push


def simulate(mu_home, mu_away, phi, ot_home_win_share, ot_decision_share):
    """One simulation: regulation grid, then the OT/SO layer added once.

    The layer moves exactly the regulation tie mass: a share
    ot_home_win_share of it to a home win (rest to an away win) for the
    moneyline, and a share ot_decision_share of the tied games gain
    exactly one goal (the OT winner) in the final totals. Shootout
    decisions add no goal (shot-derived convention, admission 4.2).
    """
    ph = goal_pmf(mu_home, phi)
    pa = goal_pmf(mu_away, phi)
    max_g = C.MAX_GOALS
    p_home_reg = p_tie = p_away_reg = 0.0
    margin = {}
    reg_total = [0.0] * (2 * max_g + 1)
    tie_total = [0.0] * (2 * max_g + 1)
    for i, pi in enumerate(ph):
        if pi == 0.0:
            continue
        for j, pj in enumerate(pa):
            if pj == 0.0:
                continue
            p = pi * pj
            reg_total[i + j] += p
            m = i - j
            margin[m] = margin.get(m, 0.0) + p
            if i > j:
                p_home_reg += p
            elif i == j:
                p_tie += p
                tie_total[i + j] += p
            else:
                p_away_reg += p
    q = ot_home_win_share
    s = ot_decision_share
    # Final totals run one goal past the regulation grid: a regulation
    # tie at the grid's top total, decided in OT, lands at 2*MAX + 1.
    # Dropping that cell would leak the folded-tail tie mass.
    final_total = []
    for k in range(2 * max_g + 2):
        reg_k = reg_total[k] if k < len(reg_total) else 0.0
        tie_k = tie_total[k] if k < len(tie_total) else 0.0
        v = reg_k - tie_k + tie_k * (1.0 - s)
        if k >= 1:
            v += tie_total[k - 1] * s
        final_total.append(v)
    return SimOutputs(
        mu_home=mu_home, mu_away=mu_away,
        p_home_reg_win=p_home_reg, p_reg_tie=p_tie, p_away_reg_win=p_away_reg,
        p_home_ml=p_home_reg + p_tie * q,
        p_away_ml=p_away_reg + p_tie * (1.0 - q),
        p_home_puck_line_minus15=sum(p for m, p in margin.items() if m >= 2),
        p_away_puck_line_plus15=1.0 - sum(p for m, p in margin.items()
                                          if m >= 2),
        reg_total_pmf=tuple(reg_total),
        final_total_pmf=tuple(final_total),
    )


# --------------------------------------------------------------------------
# Pricing (design sections 1-3: all outputs from the one simulation)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class GamePrice:
    construction_id: str
    home_team: str
    away_team: str
    target_date: int
    mu_home: float
    mu_away: float
    home_rate: TeamRate
    away_rate: TeamRate
    league_rate: float
    home_goalie: GoalieAdjustment
    away_goalie: GoalieAdjustment
    sim: SimOutputs
    params: dict
    rows_used: int
    vintage_excluded_rows: int
    degraded: bool             # either side priced off the goalie blend
    counted: bool = False
    frozen: bool = False
    validation_credit: bool = False
    play_eligible: bool = False
    evidence_state: str = "BUILD_STAGE — NOT FROZEN"


def price_game(team_rows, goalie_rows, home_team, away_team, target_date,
               params, home_starter_id=None, away_starter_id=None):
    book = build_rate_book(team_rows, target_date, params)
    for team in (home_team, away_team):
        rate = book.rates.get(team)
        if rate is None or rate.games == 0:
            raise Attempt2Refusal(
                "NO_PRIOR_GAMES", team=team, target_date=target_date,
                reason="team has no strictly-prior games in scope; the "
                       "construction does not price off an empty rate")
    home_rate = book.rates[home_team]
    away_rate = book.rates[away_team]
    home_goalie = goalie_adjustment(goalie_rows, home_team, target_date,
                                    params, starter_player_id=home_starter_id)
    away_goalie = goalie_adjustment(goalie_rows, away_team, target_date,
                                    params, starter_player_id=away_starter_id)
    mu_home_raw = home_rate.off_rate * away_rate.def_rate / book.league_rate
    mu_away_raw = away_rate.off_rate * home_rate.def_rate / book.league_rate
    mu_home = max(C.MIN_MEAN, mu_home_raw - away_goalie.delta_per_game)
    mu_away = max(C.MIN_MEAN, mu_away_raw - home_goalie.delta_per_game)
    sim = simulate(mu_home, mu_away, params.phi, params.ot_home_win_share,
                   params.ot_decision_share)
    return GamePrice(
        construction_id=C.CONSTRUCTION_ID,
        home_team=home_team, away_team=away_team, target_date=target_date,
        mu_home=mu_home, mu_away=mu_away,
        home_rate=home_rate, away_rate=away_rate,
        league_rate=book.league_rate,
        home_goalie=home_goalie, away_goalie=away_goalie, sim=sim,
        params={"half_life_games": params.half_life_games,
                "shrinkage_prior_games": params.shrinkage_prior_games,
                "goalie_shrinkage_games": params.goalie_shrinkage_games,
                "phi": params.phi,
                "ot_home_win_share": params.ot_home_win_share,
                "ot_decision_share": params.ot_decision_share,
                "treatment": params.treatment},
        rows_used=book.rows_used,
        vintage_excluded_rows=(book.vintage_excluded_rows
                               + home_goalie.vintage_excluded_rows
                               + away_goalie.vintage_excluded_rows),
        degraded=home_goalie.degraded or away_goalie.degraded,
    )
