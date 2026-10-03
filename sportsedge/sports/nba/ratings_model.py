"""Minimal online NBA team-rating model (margin + total) from final scores only.

Each team carries an offensive rating O (points scored above league average) and a
defensive rating D (points allowed above league average). Before a game:

    home_pts = L + H/2 + O_home + D_away
    away_pts = L - H/2 + O_away + D_home

After the game every term moves toward the observed score by a fixed step ``k``.
At each new season ratings shrink toward zero by ``carry``. Inputs are results
only (dates, teams, scores) -- no market data -- so predictions for a game use
strictly earlier games. This module grants no betting authority by itself; a
market is a bet only if the out-of-sample backtest in
``scripts/backtest_nba_ratings_vs_lines.py`` validates it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping


@dataclass
class NBARatingsParams:
    k: float = 0.05          # per-game step for team O/D
    k_league: float = 0.01   # per-game step for league average
    k_hca: float = 0.002     # per-game step for home advantage
    carry: float = 0.6       # fraction of rating kept across seasons
    init_league: float = 100.0
    init_hca: float = 3.0


@dataclass
class NBARatings:
    params: NBARatingsParams = field(default_factory=NBARatingsParams)
    off: dict = field(default_factory=dict)
    dfn: dict = field(default_factory=dict)
    games: dict = field(default_factory=dict)
    league: float | None = None
    hca: float | None = None
    season: object = None

    def __post_init__(self) -> None:
        if self.league is None:
            self.league = self.params.init_league
        if self.hca is None:
            self.hca = self.params.init_hca

    def start_season(self, season: object) -> None:
        if season == self.season:
            return
        c = self.params.carry
        self.off = {t: v * c for t, v in self.off.items()}
        self.dfn = {t: v * c for t, v in self.dfn.items()}
        self.games = {t: 0 for t in self.games}
        self.season = season

    def predict(self, home: str, away: str, *, neutral: bool = False) -> tuple[float, float]:
        h = 0.0 if neutral else self.hca
        hp = self.league + h / 2 + self.off.get(home, 0.0) + self.dfn.get(away, 0.0)
        ap = self.league - h / 2 + self.off.get(away, 0.0) + self.dfn.get(home, 0.0)
        return hp, ap

    def margin_total(self, home: str, away: str, *, neutral: bool = False) -> tuple[float, float]:
        hp, ap = self.predict(home, away, neutral=neutral)
        return hp - ap, hp + ap

    def update(self, home: str, away: str, home_pts: float, away_pts: float, *, neutral: bool = False) -> None:
        p = self.params
        hp, ap = self.predict(home, away, neutral=neutral)
        eh, ea = home_pts - hp, away_pts - ap
        self.off[home] = self.off.get(home, 0.0) + p.k * eh
        self.dfn[away] = self.dfn.get(away, 0.0) + p.k * eh
        self.off[away] = self.off.get(away, 0.0) + p.k * ea
        self.dfn[home] = self.dfn.get(home, 0.0) + p.k * ea
        self.league += p.k_league * (eh + ea) / 2
        if not neutral:
            self.hca += p.k_hca * (eh - ea)
        for t in (home, away):
            self.games[t] = self.games.get(t, 0) + 1


def replay(games: Iterable[Mapping], params: NBARatingsParams | None = None, *, on_pre=None) -> NBARatings:
    """Walk games in date order. ``on_pre(game, ratings)`` sees the pre-game state."""
    r = NBARatings(params or NBARatingsParams())
    for g in sorted(games, key=lambda x: (x["date"], str(x["home"]))):
        r.start_season(g["season"])
        if on_pre is not None:
            on_pre(g, r)
        r.update(g["home"], g["away"], float(g["home_pts"]), float(g["away_pts"]))
    return r
