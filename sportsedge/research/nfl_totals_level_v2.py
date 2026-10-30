"""NFL totals LEVEL v2 — recency-weighted, cross-season-carryover level
model. RESEARCH CANDIDATE ONLY (not production; nothing imports it).

Preregistration: research/nfl_totals_level_v2_20261017/
PREREG_NFL_TOTALS_LEVEL_V2.md (SHA-256 locked in SPEC_HASHES.txt).

Successor to the LEVEL v1 candidate (research/nfl-totals-level-model-
20261016, verdict DOES_NOT_BEAT_BASELINE). v1's report named the
binding error as level TRACKING: a same-season expanding average that
restarts each September and lags level shifts. v2 tests exactly one
hypothesis — a level estimate that MOVES FASTER (exponential recency
weighting) and DOES NOT RESTART (decayed cross-season carryover) beats
the frozen prior and the climatology baselines. Every constant below
is fixed by the preregistration; changing one forks the prereg.

All functions are pure and deterministic. Callers own the PIT rule:
pass only games strictly before the fixture's kickoff (identical
kickoff instants never see each other).
"""
from __future__ import annotations

from typing import Iterable, Sequence, Tuple

LEAGUE_HALF_LIFE_GAMES = 128.0   # league level: EW half-life, in games
TEAM_HALF_LIFE_GAMES = 6.0       # team residuals: EW half-life, team-games
SEASON_CARRYOVER = 0.5           # extra weight factor per season boundary
KAPPA = 3.0                      # shrinkage of team residuals toward 0
LEAGUE_FALLBACK = 22.0           # points per team-game, empty history
HFA_HALF = 0.75                  # half the production HFA of 1.5
TOTAL_SD = 13.5                  # production total sd, FIXED


def league_level(prior_half_totals: Sequence[float],
                 half_life: float = LEAGUE_HALF_LIFE_GAMES) -> float:
    """EW mean of per-team-game points over strictly-prior games.

    prior_half_totals: chronological (oldest first) values of
    game_total / 2 for every strictly-prior game, across seasons.
    The most recent game has age 0 -> weight 1; age k -> 0.5**(k/H).
    """
    n = len(prior_half_totals)
    if n == 0:
        return LEAGUE_FALLBACK
    num = den = 0.0
    for i, v in enumerate(prior_half_totals):
        w = 0.5 ** ((n - 1 - i) / half_life)
        num += w * v
        den += w
    return num / den


def team_residuals(history: Iterable[Tuple[int, float, float]],
                   current_season: int,
                   half_life: float = TEAM_HALF_LIFE_GAMES,
                   carryover: float = SEASON_CARRYOVER,
                   kappa: float = KAPPA) -> Tuple[float, float]:
    """(off_res, def_res) shrunk toward 0.

    history: chronological (oldest first) tuples
      (season, pf - L_at_game, pa - L_at_game)
    for the team's strictly-prior games, where L_at_game is the league
    level computed strictly before THAT game (no lookahead).
    Weight of a game with team-game age k (0 = most recent) from a
    season s <= current_season:
      0.5**(k/H) * carryover**(current_season - s).
    Shrunk residual = sum(w*r) / (sum(w) + kappa).
    """
    rows = list(history)
    n = len(rows)
    so = sd = sw = 0.0
    for i, (season, off_r, def_r) in enumerate(rows):
        gap = current_season - season
        if gap < 0:
            raise ValueError("history row from a future season")
        w = (0.5 ** ((n - 1 - i) / half_life)) * (carryover ** gap)
        so += w * off_r
        sd += w * def_r
        sw += w
    return so / (sw + kappa), sd / (sw + kappa)


def expected_scores(league: float, home_res: Tuple[float, float],
                    away_res: Tuple[float, float],
                    hfa_half: float = HFA_HALF) -> Tuple[float, float]:
    """(E_home, E_away): league level plus the average of a team's
    offensive residual and its opponent's defensive residual."""
    h_off, h_def = home_res
    a_off, a_def = away_res
    e_home = league + (h_off + a_def) / 2.0 + hfa_half
    e_away = league + (a_off + h_def) / 2.0 - hfa_half
    return e_home, e_away
