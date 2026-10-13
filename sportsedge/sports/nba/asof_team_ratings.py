"""As-of NBA team possession/pace/efficiency ratings (research only).

Ratings are fit ONLY on games whose verified start is strictly before
``as_of``. Inputs are sorted canonically before any arithmetic, so the
result is independent of input order and of any game at/after ``as_of``.

Model (opponent-adjusted, shrunk to league mean):
  possessions  = FGA - ORB + TOV + 0.44 * FTA   (per team, averaged per game)
  pace_g       = league_pace + pace_h + pace_a
  home_pts     = pace_g * (league_eff + off_h + def_a) / 100 + hca / 2
  away_pts     = pace_g * (league_eff + off_a + def_h) / 100 - hca / 2
No rest/back-to-back/travel term: ``rest_adj`` is DISABLED (exactly 0) by
owner ruling until it shows incremental value. No odds enter this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Iterable, Mapping

VERSION = "NBA_ASOF_TEAM_RATINGS_V1_20261013"
REST_ADJ = 0.0  # owner ruling: disabled pending incremental value


@dataclass(frozen=True)
class NBAGame:
    game_id: str
    start: datetime
    home: str
    away: str
    home_points: int
    away_points: int
    home_possessions: float
    away_possessions: float

    def validate(self) -> None:
        if self.start.tzinfo is None or self.start.utcoffset() is None:
            raise ValueError("GAME_START_TIMEZONE_REQUIRED")
        if not self.home or not self.away or self.home == self.away:
            raise ValueError("DISTINCT_TEAMS_REQUIRED")
        for v in (self.home_possessions, self.away_possessions):
            if not isfinite(v) or not 60 <= v <= 160:
                raise ValueError("POSSESSIONS_IMPLAUSIBLE")
        if min(self.home_points, self.away_points) < 0:
            raise ValueError("POINTS_INVALID")


def possessions(box: Mapping[str, str]) -> float:
    """Standard estimate from an ESPN team box; raises if any field missing."""
    fga = int(str(box["fieldGoalsMade-fieldGoalsAttempted"]).split("-")[1])
    fta = int(str(box["freeThrowsMade-freeThrowsAttempted"]).split("-")[1])
    orb = int(box["offensiveRebounds"])
    tov = int(box.get("totalTurnovers", box["turnovers"]))
    return fga - orb + tov + 0.44 * fta


@dataclass(frozen=True)
class NBATeamRatings:
    as_of: datetime
    games_used: int
    league_pace: float
    league_eff: float
    hca: float
    pace: Mapping[str, float]
    off: Mapping[str, float]
    deff: Mapping[str, float]
    games_by_team: Mapping[str, int]
    rest_adj: float = REST_ADJ
    version: str = VERSION

    def predict(self, home: str, away: str) -> dict:
        for t in (home, away):
            if t not in self.games_by_team:
                raise ValueError("TEAM_HAS_NO_PRIOR_GAMES:" + t)
        pace = self.league_pace + self.pace[home] + self.pace[away]
        hp = pace * (self.league_eff + self.off[home] + self.deff[away]) / 100 + self.hca / 2
        ap = pace * (self.league_eff + self.off[away] + self.deff[home]) / 100 - self.hca / 2
        return {"possessions": pace, "home_points": hp, "away_points": ap,
                "margin": hp - ap, "total": hp + ap, "rest_adj": self.rest_adj,
                "version": self.version}


def fit_asof(games: Iterable[NBAGame], as_of: datetime, *, shrink_games: float = 8.0,
             iterations: int = 25) -> NBATeamRatings:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("AS_OF_TIMEZONE_REQUIRED")
    prior = sorted((g for g in games if g.start < as_of),
                   key=lambda g: (g.start, g.game_id))
    seen = set()
    for g in prior:
        g.validate()
        if g.game_id in seen:
            raise ValueError("DUPLICATE_GAME_ID:" + g.game_id)
        seen.add(g.game_id)
    if len(prior) < 30:
        raise ValueError("FEWER_THAN_30_PRIOR_GAMES")
    n = len(prior)
    poss = [(g.home_possessions + g.away_possessions) / 2 for g in prior]
    league_pace = sum(poss) / n
    league_eff = sum(100 * (g.home_points + g.away_points) / (2 * p)
                     for g, p in zip(prior, poss)) / n
    hca = sum(g.home_points - g.away_points for g in prior) / (n + 50.0)  # shrunk to 0
    teams = sorted({t for g in prior for t in (g.home, g.away)})
    cnt = {t: 0 for t in teams}
    for g in prior:
        cnt[g.home] += 1
        cnt[g.away] += 1
    pace = {t: 0.0 for t in teams}
    off = {t: 0.0 for t in teams}
    deff = {t: 0.0 for t in teams}
    for _ in range(iterations):
        sp = {t: 0.0 for t in teams}
        so = {t: 0.0 for t in teams}
        sd = {t: 0.0 for t in teams}
        for g, p in zip(prior, poss):
            # pace residual shared by both teams
            sp[g.home] += p - league_pace - pace[g.away]
            sp[g.away] += p - league_pace - pace[g.home]
            he = 100 * (g.home_points - hca / 2) / p
            ae = 100 * (g.away_points + hca / 2) / p
            so[g.home] += he - league_eff - deff[g.away]
            so[g.away] += ae - league_eff - deff[g.home]
            sd[g.home] += ae - league_eff - off[g.away]
            sd[g.away] += he - league_eff - off[g.home]
        pace = {t: sp[t] / (cnt[t] + shrink_games) for t in teams}
        off = {t: so[t] / (cnt[t] + shrink_games) for t in teams}
        deff = {t: sd[t] / (cnt[t] + shrink_games) for t in teams}
    return NBATeamRatings(as_of, n, league_pace, league_eff, hca,
                          pace, off, deff, cnt)
