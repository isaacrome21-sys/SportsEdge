"""NBA team-total and period-total engine — the Oct 18 calibration
construction (B4 team totals; B11 quarter totals), implemented as an
engine. This module IS the construction scored by the backtest-everything
sweep, not a new model:

* Spec: ``backtest_everything_20261018/specs/SPEC_NBA_GAME_LEVEL_V1.md``
  (SHA-256 cc96783ffeac0074607a3d1869e4a6bea381f0c8ba3188395ad1d851a705fd00,
  hashed before scoring). Results:
  ``backtest_everything_20261018/results/nba_game_level_results.json``
  (evidence label EXECUTED_20261018).
* B4 TEAM TOTALS: candidate = ``NBARatings.predict()`` team points from
  ``sportsedge/sports/nba/ratings_model.py`` with **committed default
  parameters**, walked in date order, predictions taken pre-game
  (strictly earlier games only). Calibration BEATS_BASELINE vs both
  climatology baselines (MAE 8.9975 vs B1 9.5411 / B2 9.8275,
  n=15,506 team-games, seasons 2015–2021, SBR archive).
* B11 QUARTER TOTALS: candidate quarter-q points for a team =
  share_q x that team's ratings-predicted game points, where the shares
  come from ``fit_period_parameters`` in
  ``sportsedge/sports/nba/period_history.py`` fitted ONCE on games with
  season <= 2014 under the spec's declared mapping (tipoff = game date
  00:00 UTC, observed_at = next day 00:00 UTC, fit as_of 2015-10-01 UTC;
  published fit version NBA_PERIOD_FIT_V1:310b42f5bc41). Calibration
  BEATS_BASELINE vs both baselines (MAE 4.6103 vs B1 4.7070 / B2 4.7099,
  n=62,024 team-quarters). Half forms were NOT separately scored by the
  sweep (readiness verdict: NOT_EVALUATED); game-level quarter/half
  totals were not scored either. This engine derives them as exact
  mechanical sums of the two scored primitives (half share = sum of its
  two quarter shares; game period total = home + away team period
  totals) — the same construction aggregated, not a new model — and
  the build screen scores those forms for the first time, labeled as
  first screens, never as reproductions.

Sufficiency gates (the spec's scored-population warmup gates, both
computable point-in-time, so both gate live forecasts): a team must
have >= 10 prior in-season games and the league >= 200 prior in-season
team-games, all strictly before the target game. Below either gate the
engine refuses fail-closed with a named reason.

Period-fit gate: the construction's shares are a property of the
frozen fit protocol (span seasons <= 2014). If the supplied history
carries no quarter scores in that span, the fit cannot be reproduced
and period forms refuse with ``NBA_PERIOD_FIT_HISTORY_MISSING`` while
team totals still price. The maintained sportsdataverse assets carry
NO quarter scores at all (verified 2026-10-20: the
``nba_stats_team_boxscores`` release asset has full-game team stats
only; the player-boxscores asset likewise), so on the maintained data
path period forecasts refuse ``NBA_PERIOD_HISTORY_UNAVAILABLE`` —
period outcomes are NO_DATA there; only the static SBR archive (the
source the repo's own ratings backtest cites) carries quarter scores,
and it is the screen's vintage.

The engine emits the sanctioned point forecasts (the exact quantities
the calibration screen scores). No distributional conversion is part
of this construction, and none is invented here.

Calibration is not validation: no market leg exists for these
families (no team-total or period lines in the historical archive;
period lines are not in the DK capture scope), the readiness verdict
is NO_MARKET_TEST / NO-GO for play, and the NBA game-market families
(moneyline / spread / game total) carry a separate FAILED_VALIDATION
accuracy-gap verdict that this module does not touch. This module
grants no PLAY, staking or official authority and changes no family's
registration or eligibility state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Mapping, Optional, Sequence

from sportsedge.sports.nba.period_history import (
    NBAPeriodObservation,
    fit_period_parameters,
)
from sportsedge.sports.nba.periods import NBAPeriodParameters
from sportsedge.sports.nba.ratings_model import NBARatings, NBARatingsParams

ENGINE_ID = "NBA_TEAM_PERIOD_RATINGS_V1"

# The spec's scored-population warmup gates (SPEC_NBA_GAME_LEVEL_V1,
# "Scoring"): both are point-in-time computable, so both gate pricing.
MIN_TEAM_PRIOR_GAMES = 10
MIN_LEAGUE_PRIOR_TEAM_GAMES = 200

# The frozen period-fit protocol (spec, "Candidate"): fit once on
# seasons <= 2014, observations mapped at day granularity, fit as-of
# set after that span. These are construction constants of this engine
# version — refitting on any other span would be a different version.
PERIOD_FIT_MAX_SEASON = 2014
PERIOD_FIT_AS_OF = datetime(2015, 10, 1, tzinfo=timezone.utc)

# Named fail-closed refusals.
REFUSAL_TEAM_NOT_IN_HISTORY = "NBA_TEAM_PERIOD_TEAM_NOT_IN_HISTORY"
REFUSAL_INSUFFICIENT_TEAM_PRIORS = "NBA_TEAM_PERIOD_INSUFFICIENT_TEAM_PRIORS"
REFUSAL_INSUFFICIENT_LEAGUE_PRIORS = "NBA_TEAM_PERIOD_INSUFFICIENT_LEAGUE_PRIORS"
REFUSAL_PERIOD_FIT_HISTORY_MISSING = "NBA_PERIOD_FIT_HISTORY_MISSING"
REFUSAL_PERIOD_HISTORY_UNAVAILABLE = "NBA_PERIOD_HISTORY_UNAVAILABLE"
REFUSAL_TARGET_INVALID = "NBA_TEAM_PERIOD_TARGET_INVALID"

CALIBRATION_LABEL = "CALIBRATION_ONLY_NO_MARKET_LEG"


def _game_date(g: Mapping) -> str:
    d = g["date"]
    return d.isoformat() if isinstance(d, date) else str(d)


def _validate_game(g: Mapping) -> None:
    for key in ("date", "season", "home", "away", "home_pts", "away_pts"):
        if key not in g:
            raise ValueError(f"game history row missing {key!r}: {g!r}")
    if g["home"] == g["away"]:
        raise ValueError(f"game history row has identical teams: {g!r}")
    for key in ("home_pts", "away_pts"):
        v = float(g[key])
        if v < 0:
            raise ValueError(f"game history row has negative points: {g!r}")
    for key in ("home_quarters", "away_quarters"):
        if key in g and g[key] is not None:
            qs = tuple(g[key])
            if len(qs) != 4 or any(float(x) < 0 for x in qs):
                raise ValueError(
                    f"game history row has malformed {key}: {g!r}")


def period_observations(games: Iterable[Mapping], *, source: str,
                        source_version: str) -> list[NBAPeriodObservation]:
    """Map game rows with quarter scores to the repo's PIT period
    observations, at day granularity exactly as the spec declares:
    tipoff = game date 00:00 UTC, observed_at = next day 00:00 UTC."""
    rows = []
    for g in games:
        if g.get("home_quarters") is None or g.get("away_quarters") is None:
            continue
        d = date.fromisoformat(_game_date(g))
        tip = datetime.combine(d, time(0, 0), tzinfo=timezone.utc)
        gid = str(g.get("game_id") or f"{_game_date(g)}-{g['home']}-{g['away']}")
        rows.append(NBAPeriodObservation(
            game_id=gid, tipoff=tip, observed_at=tip + timedelta(days=1),
            home_quarters=tuple(int(x) for x in g["home_quarters"]),
            away_quarters=tuple(int(x) for x in g["away_quarters"]),
            source=source, source_version=source_version))
    return rows


def fit_period_shares(games: Iterable[Mapping], *, source: str,
                      source_version: str) -> NBAPeriodParameters:
    """The frozen fit: observations from games with
    season <= PERIOD_FIT_MAX_SEASON only, fitted with
    ``fit_period_parameters`` as of PERIOD_FIT_AS_OF. Raises ValueError
    (from the repo fitter) when no eligible history exists."""
    span = [g for g in games if int(g["season"]) <= PERIOD_FIT_MAX_SEASON]
    obs = period_observations(span, source=source,
                              source_version=source_version)
    if not obs:
        raise ValueError(REFUSAL_PERIOD_FIT_HISTORY_MISSING)
    return fit_period_parameters(obs, as_of=PERIOD_FIT_AS_OF)


def games_from_team_boxscores(rows: Iterable[Mapping],
                              game_dates: Mapping[str, str]) -> list[dict]:
    """Adapt sportsdataverse ``nba_stats_team_boxscores``-shaped rows
    (one row per team per game: game_id, side home/away, team_tricode,
    points, season) plus a game_id -> ISO date map into engine game
    rows. The asset carries no dates and no quarter scores, so dates
    join on game_id (the repo's maintained-pull convention) and the
    resulting games carry no quarter data — period forms will refuse
    NO_DATA on this path. Fail-closed: a game_id missing from
    ``game_dates``, a game without exactly one home and one away row,
    or a duplicated side raises ValueError."""
    by_game: dict[str, dict] = {}
    for r in rows:
        gid = str(r["game_id"])
        side = str(r["side"]).strip().lower()
        if side not in ("home", "away"):
            raise ValueError(f"team boxscore row has bad side: {r!r}")
        slot = by_game.setdefault(gid, {})
        if side in slot:
            raise ValueError(f"duplicate {side} row for game {gid}")
        slot[side] = r
    games = []
    for gid, slot in sorted(by_game.items()):
        if "home" not in slot or "away" not in slot:
            raise ValueError(f"game {gid} lacks a home or away row")
        if gid not in game_dates:
            raise ValueError(f"game {gid} missing from game_dates")
        h, a = slot["home"], slot["away"]
        games.append({
            "game_id": gid, "date": str(game_dates[gid]),
            "season": int(h["season"]),
            "home": str(h["team_tricode"]), "away": str(a["team_tricode"]),
            "home_pts": float(h["points"]), "away_pts": float(a["points"]),
            "home_quarters": None, "away_quarters": None})
    return games


@dataclass
class NBATeamPeriodEngine:
    """Stateful walk over game history in (date, home) order — the
    repo replay order. ``forecast`` reads the pre-game state;
    ``consume`` advances ratings and the expanding in-season baseline
    accumulators with a game's finals. For a single live forecast use
    :func:`price_game`, which consumes only strictly-earlier games."""

    params: NBARatingsParams = field(default_factory=NBARatingsParams)
    ratings: NBARatings = field(default_factory=NBARatings)
    period_params: Optional[NBAPeriodParameters] = None
    _season: Optional[int] = None
    _seen_teams: set = field(default_factory=set)
    _team_games: dict = field(default_factory=dict)
    _team_pts: dict = field(default_factory=dict)
    _team_q: dict = field(default_factory=dict)
    _team_h: dict = field(default_factory=dict)
    _league_games: int = 0
    _league_pts: float = 0.0
    _league_q: list = field(default_factory=lambda: [0.0] * 4)
    _league_h: list = field(default_factory=lambda: [0.0] * 2)

    # -- season / state management ------------------------------------
    def _advance_season(self, season: int) -> None:
        if season == self._season:
            return
        self._season = season
        self.ratings.start_season(season)
        self._team_games = {}
        self._team_pts = {}
        self._team_q = {}
        self._team_h = {}
        self._league_games = 0
        self._league_pts = 0.0
        self._league_q = [0.0] * 4
        self._league_h = [0.0] * 2

    # -- period fit ----------------------------------------------------
    def fit_periods(self, games: Iterable[Mapping], *, source: str,
                    source_version: str) -> NBAPeriodParameters:
        self.period_params = fit_period_shares(
            games, source=source, source_version=source_version)
        return self.period_params

    # -- walk ----------------------------------------------------------
    def consume(self, g: Mapping) -> None:
        _validate_game(g)
        season = int(g["season"])
        self._advance_season(season)
        home, away = str(g["home"]), str(g["away"])
        self._seen_teams.add(home)
        self._seen_teams.add(away)
        hp, ap = float(g["home_pts"]), float(g["away_pts"])
        self.ratings.update(home, away, hp, ap)
        hq = g.get("home_quarters")
        aq = g.get("away_quarters")
        for team, pts, qs in ((home, hp, hq), (away, ap, aq)):
            self._team_games[team] = self._team_games.get(team, 0) + 1
            self._team_pts[team] = self._team_pts.get(team, 0.0) + pts
            tq = self._team_q.setdefault(team, [0.0] * 4)
            th = self._team_h.setdefault(team, [0.0] * 2)
            self._league_games += 1
            self._league_pts += pts
            if qs is not None:
                qs = tuple(float(x) for x in qs)
                for q in range(4):
                    tq[q] += qs[q]
                    self._league_q[q] += qs[q]
                th[0] += qs[0] + qs[1]
                th[1] += qs[2] + qs[3]
                self._league_h[0] += qs[0] + qs[1]
                self._league_h[1] += qs[2] + qs[3]

    # -- forecast ------------------------------------------------------
    def forecast(self, home: str, away: str, *, season: int,
                 target_date: str) -> dict:
        home, away = str(home), str(away)
        base = {"engine_id": ENGINE_ID, "home": home, "away": away,
                "season": int(season), "target_date": str(target_date),
                "calibration_label": CALIBRATION_LABEL,
                "market_test": "NONE"}
        if home == away:
            return {**base, "status": "REFUSED",
                    "reason": REFUSAL_TARGET_INVALID}
        self._advance_season(int(season))
        hg = self._team_games.get(home, 0)
        ag = self._team_games.get(away, 0)
        priors = {"home_team_games": hg, "away_team_games": ag,
                  "league_team_games": self._league_games}
        for team, n in ((home, hg), (away, ag)):
            if team not in self._seen_teams:
                return {**base, "status": "REFUSED",
                        "reason": REFUSAL_TEAM_NOT_IN_HISTORY,
                        "team": team, "priors": priors}
        if hg < MIN_TEAM_PRIOR_GAMES or ag < MIN_TEAM_PRIOR_GAMES:
            return {**base, "status": "REFUSED",
                    "reason": REFUSAL_INSUFFICIENT_TEAM_PRIORS,
                    "priors": priors}
        if self._league_games < MIN_LEAGUE_PRIOR_TEAM_GAMES:
            return {**base, "status": "REFUSED",
                    "reason": REFUSAL_INSUFFICIENT_LEAGUE_PRIORS,
                    "priors": priors}

        hp, ap = self.ratings.predict(home, away)
        lg_mean = self._league_pts / self._league_games
        baselines = {
            "home_team_mean": self._team_pts[home] / hg,
            "away_team_mean": self._team_pts[away] / ag,
            "league_mean": lg_mean,
            "home_quarter_means": [
                self._team_q[home][q] / hg for q in range(4)],
            "away_quarter_means": [
                self._team_q[away][q] / ag for q in range(4)],
            "league_quarter_means": [
                self._league_q[q] / self._league_games for q in range(4)],
            "home_half_means": [
                self._team_h[home][h] / hg for h in range(2)],
            "away_half_means": [
                self._team_h[away][h] / ag for h in range(2)],
            "league_half_means": [
                self._league_h[h] / self._league_games for h in range(2)],
        }
        out = {**base, "status": "PRICED", "sufficiency_met": True,
               "priors": priors,
               "team_totals": {"home": hp, "away": ap},
               "baselines": baselines}
        if self.period_params is None:
            out["periods"] = {"status": "REFUSED",
                              "reason": REFUSAL_PERIOD_HISTORY_UNAVAILABLE}
            return out
        shares = self.period_params.quarter_shares
        half_shares = (shares[0] + shares[1], shares[2] + shares[3])
        out["periods"] = {
            "status": "PRICED",
            "fit_version": self.period_params.version,
            "quarter_shares": list(shares),
            "team_quarter_totals": {
                "home": [shares[q] * hp for q in range(4)],
                "away": [shares[q] * ap for q in range(4)]},
            "game_quarter_totals": [
                shares[q] * (hp + ap) for q in range(4)],
            "team_half_totals": {
                "home": [half_shares[h] * hp for h in range(2)],
                "away": [half_shares[h] * ap for h in range(2)]},
            "game_half_totals": [
                half_shares[h] * (hp + ap) for h in range(2)],
        }
        return out


def price_game(history: Iterable[Mapping], home: str, away: str, *,
               season: int, target_date: str,
               period_source: Optional[tuple] = None) -> dict:
    """Live single-game forecast: build the walk from history games
    dated strictly before ``target_date`` (date granularity — a
    same-date final is never consumed), then forecast. ``period_source``
    is an optional ``(source, source_version)`` pair enabling the
    frozen period fit from the history's fit-span quarter scores."""
    games = []
    for g in history:
        _validate_game(g)
        if _game_date(g) < str(target_date):
            games.append(g)
    games.sort(key=lambda g: (_game_date(g), str(g["home"])))
    eng = NBATeamPeriodEngine()
    if period_source is not None:
        try:
            eng.fit_periods(games, source=period_source[0],
                            source_version=period_source[1])
        except ValueError:
            eng.period_params = None
    for g in games:
        eng.consume(g)
    out = eng.forecast(home, away, season=season, target_date=target_date)
    if (period_source is not None and out.get("status") == "PRICED"
            and out["periods"]["status"] == "REFUSED"):
        out["periods"] = {"status": "REFUSED",
                          "reason": REFUSAL_PERIOD_FIT_HISTORY_MISSING}
    return out
