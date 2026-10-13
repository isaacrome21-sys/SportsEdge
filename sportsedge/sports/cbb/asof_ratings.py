"""CBB as-of team ratings (pace/efficiency, opponent-adjusted, shrunk, home court).

Spec: docs/CBB_ASOF_RATINGS_PREREG_20261013.md. Research only. Games train only
when completed and start + 3h <= cutoff. Ordering is canonical. Illinois schools
(ESPN ids in IL_COLLEGE_ESPN_IDS, #2148) may appear as training opponents but
are BLOCKED ILLINOIS_COLLEGE_EXCLUDED for any scored/playable output.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import erf, isfinite, sqrt
from typing import Iterable, Sequence

from artifacts.free_models import IL_COLLEGE_ESPN_IDS

VERSION = "CBB_ASOF_RATINGS_V1_20261013"
FINAL_BUFFER = timedelta(hours=3)
SHRINK_GAMES = 5.0
ITERATIONS = 20
FTA_COEF = 0.475


@dataclass(frozen=True)
class CBBGame:
    game_id: str
    start: datetime
    home_id: str
    away_id: str
    home_points: int
    away_points: int
    possessions: float
    neutral: bool
    completed: bool = True


def possessions(fga: float, oreb: float, tov: float, fta: float) -> float:
    return fga - oreb + tov + FTA_COEF * fta


def trainable(g: CBBGame, cutoff: datetime) -> bool:
    return g.completed and g.start + FINAL_BUFFER <= cutoff


def illinois_block(home_id: str, away_id: str) -> dict | None:
    hit = [IL_COLLEGE_ESPN_IDS[t] for t in (home_id, away_id) if str(t) in IL_COLLEGE_ESPN_IDS]
    if hit:
        return {"status": "BLOCKED", "reason": "ILLINOIS_COLLEGE_EXCLUDED", "excluded_teams": hit,
                "play_authority": False}
    return None


def _phi(x: float) -> float:
    return 0.5 * (1 + erf(x / sqrt(2)))


@dataclass
class CBBRatings:
    as_of: datetime
    games_used: int
    league_eff: float
    league_pace: float
    hca: float
    off: dict
    deff: dict
    pace: dict
    n: dict
    margin_sd: float
    total_sd: float
    version: str = VERSION

    def predict(self, home_id: str, away_id: str, *, neutral: bool) -> dict:
        block = illinois_block(home_id, away_id)
        for t in (home_id, away_id):
            if t not in self.n:
                raise ValueError("TEAM_HAS_NO_PRIOR_GAMES:" + t)
        pace = self.league_pace + self.pace[home_id] + self.pace[away_id]
        h = 0.0 if neutral else self.hca / 2
        hp = pace * (self.league_eff + self.off[home_id] + self.deff[away_id]) / 100 + h
        ap = pace * (self.league_eff + self.off[away_id] + self.deff[home_id]) / 100 - h
        out = {"home_points": hp, "away_points": ap, "margin": hp - ap, "total": hp + ap, "possessions": pace,
               "p_home_win": _phi((hp - ap) / self.margin_sd), "version": self.version,
               "status": "RESEARCH_ONLY", "play_authority": False}
        if block:
            out.update(block)
        return out

    def p_home_cover(self, pred: dict, spread_line: float) -> float:
        """P(home margin > line) where line is home's expected margin stand-in."""
        return 1 - _phi((spread_line - pred["margin"]) / self.margin_sd)

    def p_over(self, pred: dict, total_line: float) -> float:
        return 1 - _phi((total_line - pred["total"]) / self.total_sd)


def fit_asof(games: Iterable[CBBGame], cutoff: datetime) -> CBBRatings:
    if cutoff.tzinfo is None:
        raise ValueError("CUTOFF_TIMEZONE_REQUIRED")
    seen, prior = set(), []
    for g in sorted(games, key=lambda g: (g.start, g.game_id)):
        if g.game_id in seen or not trainable(g, cutoff):
            continue
        if not (isfinite(g.possessions) and 40 <= g.possessions <= 110):
            continue
        seen.add(g.game_id)
        prior.append(g)
    if len(prior) < 20:
        raise ValueError("FEWER_THAN_20_TRAINABLE_GAMES")
    nn = [g for g in prior if not g.neutral]
    hca = sum(g.home_points - g.away_points for g in nn) / len(nn) if nn else 0.0
    rows = []  # (team, opp, eff_for, pace, home_sign)
    for g in prior:
        s = 0.0 if g.neutral else 1.0
        rows.append((g.home_id, g.away_id, 100 * (g.home_points - s * hca / 2) / g.possessions, g.possessions))
        rows.append((g.away_id, g.home_id, 100 * (g.away_points + s * hca / 2) / g.possessions, g.possessions))
    eff = sum(r[2] for r in rows) / len(rows)
    lp = sum(r[3] for r in rows) / len(rows) / 2  # per-team pace contribution baseline
    teams = sorted({r[0] for r in rows})
    n = defaultdict(int)
    for r in rows:
        n[r[0]] += 1
    off = {t: 0.0 for t in teams}
    de = {t: 0.0 for t in teams}
    pc = {t: 0.0 for t in teams}
    by_t = defaultdict(list)
    by_o = defaultdict(list)
    for r in rows:
        by_t[r[0]].append(r)
        by_o[r[1]].append(r)
    for _ in range(ITERATIONS):
        off = {t: sum(r[2] - eff - de[r[1]] for r in by_t[t]) / (n[t] + SHRINK_GAMES) for t in teams}
        de = {t: sum(r[2] - eff - off[r[0]] for r in by_o[t]) / (len(by_o[t]) + SHRINK_GAMES) for t in teams}
        pc = {t: sum(r[3] - 2 * lp - pc[r[1]] for r in by_t[t]) / (n[t] + SHRINK_GAMES) for t in teams}
    league_pace = 2 * lp
    r0 = CBBRatings(cutoff, len(prior), eff, league_pace - 0.0, hca, off, de, pc, dict(n), 1.0, 1.0)
    r0.league_pace = league_pace
    # pace = league_pace + pc_h + pc_a
    mres, tres = [], []
    for g in prior:
        p = r0.predict(g.home_id, g.away_id, neutral=g.neutral)
        mres.append((g.home_points - g.away_points) - p["margin"])
        tres.append((g.home_points + g.away_points) - p["total"])
    sd = lambda v: max(1.0, sqrt(sum(x * x for x in v) / len(v)))
    r0.margin_sd, r0.total_sd = sd(mres), sd(tres)
    return r0
