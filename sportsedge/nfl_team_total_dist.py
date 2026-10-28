"""NFL_TEAM_TOTAL_DIST_V1 — point-in-time NFL team-total distribution engine.

Construction (as designed in
``research/nfl_activation_20261027/DESIGN_NFL_TEAM_TOTALS_V1.md`` and
screened in that pack's ``SCREEN_REPORT.md``; freeze package prepared in
``research/nfl_team_totals_forward_20261028/``):

For team T vs opponent O in week w of season s, using only games
completed before the game (regular season):

- sample(T) = T's same-season prior games, supplemented by T's most
  recent prior-season games until the sample reaches 8 games (or
  history exhausts). Same for O's points-allowed sample.
- G = mean team score over games of the season recorded so far; the
  previous season's full league mean in week 1 (the Part 2 league-pool
  form).
- off_T = (sum of T's sample scores + K * G) / (n + K), K = 3;
  def_O the same form on O's sample points allowed.
- mu_T = off_T * def_O / G (multiplicative opponent adjustment).
- Distribution: Negative Binomial with mean mu_T and variance
  (c * mu_T)^2, Poisson where variance <= mu; c = POOLED_CV_C, the
  pooled coefficient of variation of (score / mu) over the 2018-2019
  training seasons only. c is a training constant of this version,
  re-derived only under a new version (see ``derive_pooled_cv``).

The engine takes **no market input at all** — no spread, no total, no
line enters any feature or the probability path. A line is accepted
only by the probability *readout* helpers (``prob_over`` /
``prob_under`` / ``prob_push``), which evaluate the already-computed
distribution at a posted line; they never feed back into mu.

This is explicitly not the retired NFL_ANCHORED_RATINGS_V1 (a
market-anchored ratings blend that failed its screen and stays
retired). The market appears only as the thing the forward test must
beat, never as an input.

Point-in-time discipline: the engine is a single-pass walk-forward
over a history snapshot. A game's prediction is computed from state
recorded strictly before that game is recorded; ``record_game``
refuses anything that is not a final regular-season game, so an
unplayed or post-season game can never enter the samples. Deterministic:
no randomness anywhere in this module.

PAPER / research only. Pricing a game with this engine starts no
clock; the family's forward test counts rows only after its owner's
freeze (see the freeze package).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

import numpy as np
from scipy import stats

ENGINE_ID = "NFL_TEAM_TOTAL_DIST_V1"
MODEL_VERSION = "nfl_team_total_dist_v1"

K_SHRINK = 3.0            # Part 2 shrinkage form, K = 3
SAMPLE_CAP = 8            # prior-season supplement cap (games)
MAX_SCORE = 120           # distribution support: points 0..MAX_SCORE
TRAIN_SEASONS = (2018, 2019)

# Pooled CV of (score / mu) over the 2018-2019 training seasons,
# computed by the design screen (research/nfl_activation_20261027,
# screen_results_v1.json: pooled_cv_c) and reproduced with this engine
# by the freeze package's reproduction harness. A training constant of
# this version; changing it is a new version.
POOLED_CV_C = 0.46438741207903494

# League-mean fallback when no history exists at all (the design
# screen's week-1-of-the-file fallback).
DEFAULT_LEAGUE_MEAN = 22.0


def nb_cdf_grid(mu: float, c: float = POOLED_CV_C) -> np.ndarray:
    """CDF values F(k) for k = 0..MAX_SCORE of the construction's NB law.

    Negative Binomial with mean ``mu`` and variance ``(c * mu)^2``;
    Poisson where variance <= mu (or mu <= 0).
    """
    var = (c * mu) ** 2
    ks = np.arange(0, MAX_SCORE + 1)
    if var <= mu or mu <= 0:
        return stats.poisson.cdf(ks, max(mu, 1e-9))
    r = mu * mu / (var - mu)
    p = r / (r + mu)
    return stats.nbinom.cdf(ks, r, p)


def nb_pmf_grid(mu: float, c: float = POOLED_CV_C) -> np.ndarray:
    """PMF values P(X = k) for k = 0..MAX_SCORE (CDF differences)."""
    cdf = nb_cdf_grid(mu, c)
    pmf = np.diff(np.concatenate(([0.0], cdf)))
    return pmf


def crps_from_cdf(cdf: np.ndarray, x: int) -> float:
    """CRPS of a discrete CDF grid against realized value ``x``."""
    ks = np.arange(0, MAX_SCORE + 1)
    return float(np.sum((cdf - (x <= ks)) ** 2))


def prob_over(mu: float, line: float, c: float = POOLED_CV_C) -> float:
    """P(team points > line) under the construction's distribution."""
    cdf = nb_cdf_grid(mu, c)
    k = int(np.floor(line))
    if k < 0:
        return 1.0
    if k >= MAX_SCORE:
        return 0.0
    return float(1.0 - cdf[k])


def prob_under(mu: float, line: float, c: float = POOLED_CV_C) -> float:
    """P(team points < line) under the construction's distribution."""
    cdf = nb_cdf_grid(mu, c)
    k = int(np.ceil(line)) - 1
    if k < 0:
        return 0.0
    if k >= MAX_SCORE:
        return 1.0
    return float(cdf[k])


def prob_push(mu: float, line: float, c: float = POOLED_CV_C) -> float:
    """P(team points == line); zero unless ``line`` is a whole number."""
    if float(line) != int(line):
        return 0.0
    k = int(line)
    if k < 0 or k > MAX_SCORE:
        return 0.0
    pmf = nb_pmf_grid(mu, c)
    return float(pmf[k])


@dataclass(frozen=True)
class GameRecord:
    """One game on the schedules scale. Scores are None until final."""

    season: int
    week: int
    gameday: str            # ISO date "YYYY-MM-DD" (chronological sort key)
    game_id: str
    home_team: str
    away_team: str
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    game_type: str = "REG"

    @property
    def is_final_regular(self) -> bool:
        return (self.game_type == "REG"
                and self.home_score is not None
                and self.away_score is not None)


@dataclass(frozen=True)
class TeamTotalPrediction:
    """One team's pre-game distribution summary for one game."""

    game_id: str
    season: int
    week: int
    team: str
    opponent: str
    mu: float               # construction mean (candidate)
    off_rate: float         # shrunk offensive rate for the team
    def_rate: float         # shrunk points-allowed rate for the opponent
    league_mean: float      # G at prediction time
    b1_team_mean: float     # B1 baseline: team's unshrunk sample mean
    b2_league_mean: float   # B2 baseline: league mean G
    off_sample_n: int
    def_sample_n: int
    model_version: str = MODEL_VERSION
    engine_id: str = ENGINE_ID

    def cdf_grid(self, c: float = POOLED_CV_C) -> np.ndarray:
        return nb_cdf_grid(self.mu, c)

    def prob_over(self, line: float) -> float:
        return prob_over(self.mu, line)

    def prob_under(self, line: float) -> float:
        return prob_under(self.mu, line)


def _sort_key(game: GameRecord) -> tuple:
    # The design screen's processing order: (season, week, gameday, game_id).
    return (game.season, game.week, game.gameday, game.game_id)


class TeamTotalDistEngine:
    """Single-pass point-in-time walk-forward state for the construction.

    Feed a history snapshot through :meth:`process_snapshot` (predictions
    are emitted before each game is recorded), then price upcoming games
    with :meth:`predict_game`. State mutates only through
    :meth:`record_game`, which accepts final regular-season games only.
    """

    def __init__(self) -> None:
        # team -> chronological list of (season, score_for, score_against)
        self._history: dict[str, list[tuple[int, int, int]]] = {}
        # season -> team scores of games recorded so far in that season
        self._season_scores: dict[int, list[int]] = {}
        # season -> full-season league mean, set once the season's final
        # week has been recorded (the design screen's update rule)
        self._season_league_mean: dict[int, float] = {}
        self._season_max_week: dict[int, int] = {}

    # -- point-in-time state reads -------------------------------------

    def league_mean(self, season: int, week: int) -> float:
        """G: mean team score over the season's games recorded so far.

        Week-1 fallback (no games of ``season`` recorded yet): the
        previous season's full league mean; before any history exists,
        the mean of all recorded scores, else DEFAULT_LEAGUE_MEAN.
        """
        prior = self._season_scores.get(season, [])
        if prior:
            return float(np.mean(prior))
        prev = self._season_league_mean.get(season - 1)
        if prev is None:
            prev = float(np.mean([sf for _, sf, _ in
                                  sum(self._history.values(), [])])) \
                if self._history else DEFAULT_LEAGUE_MEAN
        return float(prev)

    def _sample(self, team: str, season: int) -> list[tuple[int, int, int]]:
        """The construction's sample: same-season priors supplemented by
        the most recent prior-season games until the sample reaches
        SAMPLE_CAP games (or history exhausts); capped at SAMPLE_CAP."""
        hist = self._history.get(team, [])
        same = [h for h in hist if h[0] == season]
        if len(same) >= SAMPLE_CAP:
            return same[-SAMPLE_CAP:]
        prior = [h for h in hist if h[0] < season]
        need = SAMPLE_CAP - len(same)
        return prior[-need:] + same if need > 0 else same

    @staticmethod
    def _shrunk_mean(values: Sequence[float], g: float) -> float:
        n = len(values)
        return (sum(values) + K_SHRINK * g) / (n + K_SHRINK)

    # -- prediction ------------------------------------------------------

    def predict_team(self, team: str, opponent: str, season: int,
                     week: int, game_id: str = "") -> TeamTotalPrediction:
        """Price one team's total from state recorded strictly before
        the game. Reads state only; never mutates it."""
        g = self.league_mean(season, week)
        s_t = self._sample(team, season)
        s_o = self._sample(opponent, season)
        off = self._shrunk_mean([h[1] for h in s_t], g)
        dfn = self._shrunk_mean([h[2] for h in s_o], g)
        mu = off * dfn / g
        b1 = float(np.mean([h[1] for h in s_t])) if s_t else g
        return TeamTotalPrediction(
            game_id=game_id, season=season, week=week, team=team,
            opponent=opponent, mu=float(mu), off_rate=float(off),
            def_rate=float(dfn), league_mean=float(g),
            b1_team_mean=float(b1), b2_league_mean=float(g),
            off_sample_n=len(s_t), def_sample_n=len(s_o))

    def predict_game(self, game: GameRecord) -> tuple[TeamTotalPrediction,
                                                       TeamTotalPrediction]:
        """Price both teams of a game from current (pre-game) state."""
        home = self.predict_team(game.home_team, game.away_team,
                                 game.season, game.week, game.game_id)
        away = self.predict_team(game.away_team, game.home_team,
                                 game.season, game.week, game.game_id)
        return home, away

    # -- state mutation --------------------------------------------------

    def record_game(self, game: GameRecord) -> None:
        """Record a final regular-season game into the samples.

        Refuses anything else (fail-closed): a game that is not final,
        or not regular-season, can never enter a sample.
        """
        if not game.is_final_regular:
            raise ValueError(
                "REFUSED_NONFINAL_OR_NONREG_GAME: "
                f"{game.game_id} type={game.game_type} "
                f"home_score={game.home_score} away_score={game.away_score}")
        season = game.season
        hs, as_ = int(game.home_score), int(game.away_score)
        self._history.setdefault(game.home_team, []).append((season, hs, as_))
        self._history.setdefault(game.away_team, []).append((season, as_, hs))
        self._season_scores.setdefault(season, []).extend([hs, as_])
        if game.week > self._season_max_week.get(season, 0):
            self._season_max_week[season] = game.week
        if game.week == self._season_max_week.get(season):
            sc = self._season_scores.get(season, [])
            if sc:
                self._season_league_mean[season] = float(np.mean(sc))

    def process_snapshot(
            self, games: Iterable[GameRecord]
    ) -> list[tuple[GameRecord, TeamTotalPrediction, TeamTotalPrediction]]:
        """Walk a history snapshot forward in the design screen's order.

        Only final regular-season games are processed, sorted by
        (season, week, gameday, game_id). Each game's predictions are
        computed from state recorded strictly before it, then the game
        is recorded. Returns (game, home_prediction, away_prediction)
        in processing order.
        """
        ordered = sorted((g for g in games if g.is_final_regular),
                         key=_sort_key)
        for g in ordered:
            cur = self._season_max_week.get(g.season, 0)
            if g.week > cur:
                self._season_max_week[g.season] = g.week
        out = []
        for g in ordered:
            home, away = self.predict_game(g)
            out.append((g, home, away))
            self.record_game(g)
        return out


def derive_pooled_cv(games: Iterable[GameRecord],
                     train_seasons: Sequence[int] = TRAIN_SEASONS) -> float:
    """Re-derive the pooled CV c from the training seasons only.

    Runs the walk-forward over ``games``; for every team-game in a
    training season, collects score / mu (mu from pre-game state), and
    returns the population standard deviation (ddof=0) of the ratios —
    the design screen's derivation, reproduced so the training constant
    is auditable against this engine rather than trusted.
    """
    engine = TeamTotalDistEngine()
    ratios: list[float] = []
    for game, home, away in engine.process_snapshot(games):
        if game.season in train_seasons:
            for pred, score in ((home, int(game.home_score)),
                                (away, int(game.away_score))):
                ratios.append(score / pred.mu if pred.mu > 0 else np.nan)
    return float(np.nanstd(np.array(ratios), ddof=0))
