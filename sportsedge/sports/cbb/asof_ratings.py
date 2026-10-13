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
NON_D1 = "NON_D1"
VERSION_V2 = "CBB_ASOF_RATINGS_V2_20261013"


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
    # IDs arrive from JSON as either positive integers or decimal strings.
    # Normalize before *both* membership and indexing: the old check used
    # str(t) for membership but t for lookup, crashing on integer IDs.
    ids = [str(t) for t in (home_id, away_id)]
    hit = [IL_COLLEGE_ESPN_IDS[t] for t in ids if t in IL_COLLEGE_ESPN_IDS]
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
    d1_ids: frozenset | None = None

    def _key(self, t: str) -> str:
        return t if self.d1_ids is None or t in self.d1_ids else NON_D1

    def predict(self, home_id: str, away_id: str, *, neutral: bool) -> dict:
        block = illinois_block(home_id, away_id)
        home_id, away_id = self._key(home_id), self._key(away_id)
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


def fit_asof(games: Iterable[CBBGame], cutoff: datetime, *, version: str = "v1",
             d1_ids: Iterable[str] | None = None) -> CBBRatings:
    """v1: raw home-margin H (pre-registered, biased). v2: H fitted jointly as the home
    residual after team strengths each iteration; non-D1 teams pooled into NON_D1."""
    if version not in {"v1", "v2"}:
        raise ValueError("VERSION_INVALID")
    d1 = frozenset(str(t) for t in d1_ids) if (version == "v2" and d1_ids is not None) else None
    if version == "v2" and d1 is None:
        raise ValueError("V2_REQUIRES_D1_IDS")
    key = (lambda t: t) if d1 is None else (lambda t: t if t in d1 else NON_D1)
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
    hca = (sum(g.home_points - g.away_points for g in nn) / len(nn) if nn else 0.0) if version == "v1" else 0.0

    def build_rows(h):
        out = []
        for g in prior:
            s = 0.0 if g.neutral else 1.0
            hk, ak = key(g.home_id), key(g.away_id)
            out.append((hk, ak, 100 * (g.home_points - s * h / 2) / g.possessions, g.possessions))
            out.append((ak, hk, 100 * (g.away_points + s * h / 2) / g.possessions, g.possessions))
        return out
    rows = build_rows(hca)
    eff = sum(r[2] for r in rows) / len(rows)
    lp = sum(r[3] for r in rows) / len(rows) / 2  # per-team pace contribution baseline
    teams = sorted({r[0] for r in rows})
    n = defaultdict(int)
    for r in rows:
        n[r[0]] += 1
    off = {t: 0.0 for t in teams}
    de = {t: 0.0 for t in teams}
    pc = {t: 0.0 for t in teams}
    def index(rows_):
        bt, bo = defaultdict(list), defaultdict(list)
        for r in rows_:
            bt[r[0]].append(r)
            bo[r[1]].append(r)
        return bt, bo
    by_t, by_o = index(rows)
    for _ in range(ITERATIONS):
        if version == "v2" and nn:
            res = []
            for g in nn:
                hk, ak = key(g.home_id), key(g.away_id)
                pace_g = 2 * lp + pc[hk] + pc[ak]
                res.append((g.home_points - g.away_points) - pace_g * ((off[hk] + de[ak]) - (off[ak] + de[hk])) / 100)
            hca = sum(res) / len(res)
            rows = build_rows(hca)
            by_t, by_o = index(rows)
        off = {t: sum(r[2] - eff - de[r[1]] for r in by_t[t]) / (n[t] + SHRINK_GAMES) for t in teams}
        de = {t: sum(r[2] - eff - off[r[0]] for r in by_o[t]) / (len(by_o[t]) + SHRINK_GAMES) for t in teams}
        pc = {t: sum(r[3] - 2 * lp - pc[r[1]] for r in by_t[t]) / (n[t] + SHRINK_GAMES) for t in teams}
    league_pace = 2 * lp
    r0 = CBBRatings(cutoff, len(prior), eff, league_pace, hca, off, de, pc, dict(n), 1.0, 1.0,
                    VERSION if version == "v1" else VERSION_V2, d1)
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
