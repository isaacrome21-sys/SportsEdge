"""NFL_FIRST_TD_V1 -- design-stage construction (UNPINNED, research only).

Implements DESIGN_NFL_GAME_PROPS_TD_V1.md section 2 (research/
nfl_activation_20261027/) exactly:

  P(p scores the game's first TD) = P(T scores first) x P(p | T first)

  Stage 1: P(T scores the game's first TD) from T's point-in-time
  first-TD frequency (share of T's games in sample where T scored
  first), shrunk toward the league rate with the Part 2 K = 3 form
  on game counts: (n_first + K * G) / (n_games + K). First
  possession is the league-average defer/receive mixture by
  construction (no coin-toss input exists at capture time; the
  design says so). The no-TD outcome is carried at its point-in-time
  league rate.

  Stage 2: P(p | T first) from p's point-in-time first-TD share,
  shrunk toward p's share of T's any touchdowns (the anytime
  profile) with K1 = 3 on first-TD counts; the anytime share is
  itself the Part 2-style shrunk estimate (K = 3) toward the
  positional league pool (RB/WR/TE/QB first-TD shares). Defensive /
  return first TDs are a single pooled outcome class (DEF/ST) with
  its own point-in-time rate, at both levels. Probabilities are
  renormalized over the candidate board + the DEF/ST class + the
  no-TD outcome (the design's renormalization step).

Samples are same-season prior games only (the Part 2 sample rule).
Pool terms (the G of each shrinkage) follow the Part 2 calibration
convention for cold starts: for games in weeks 1-3 the pool is the
previous season's full-season pool; player and team counts are
always same-season prior games. (Reading recorded in the screen
report; the design fixes the sample rule and the shrinkage form,
the Part 2 calibration prereg fixes the week 1-3 fallback.)

This module is NOT the frozen anytime-TD family and confers no
pricing authority: the framework config stays UNPINNED until the
owner freeze that follows this construction's calibration screen.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Mapping, Sequence

VERSION = "NFL_FIRST_TD_V1"

K_STAGE1 = 3.0   # Part 2 K form on game counts (design section 2)
K1_STAGE2 = 3.0  # first-TD counts toward the anytime share (design)
K_ANYTIME = 3.0  # Part 2-style shrunk anytime estimate (design)

DEF_RETURN_TYPES = frozenset({
    "INTERCEPTION_RETURN", "FUMBLE_RETURN", "KICKOFF_RETURN",
    "PUNT_RETURN", "BLOCKED_KICK_RETURN",
})
OFFENSIVE_TYPES = frozenset({"RUSHING", "RECEIVING",
                             "OTHER_EXPLICIT_CREDIT"})
POSITION_GROUPS = ("QB", "RB", "WR", "TE", "OTHER")

# Declared structural fallback, used only if no pool source exists at
# all (never the case inside the admitted panel window, where 2019
# supplies the 2020 cold start). Not fitted on any data.
UNIFORM_POOL_FIRST_POS = {g: 1.0 / len(POSITION_GROUPS)
                          for g in POSITION_GROUPS}
UNIFORM_POOL_ANY_POS = dict(UNIFORM_POOL_FIRST_POS)


def position_group(position: str | None) -> str:
    pos = (position or "").strip().upper()
    if pos == "QB":
        return "QB"
    if pos in {"RB", "FB", "HB"}:
        return "RB"
    if pos in {"WR", "TE"}:
        return pos
    return "OTHER"


@dataclass
class Pools:
    """League pool terms (the G of every shrinkage), point-in-time."""
    games: int
    no_td_rate: float
    team_first_rate: float          # per team-game: (1 - no_td) / 2
    first_pos: dict                 # group -> share of offensive 1st TDs
    any_pos: dict                   # group -> share of offensive any TDs
    def_any_share: float            # def/return share of ALL team TDs
    def_first_share: float          # def/return share of ALL first TDs

    @classmethod
    def uniform(cls) -> "Pools":
        return cls(games=0, no_td_rate=0.05, team_first_rate=0.475,
                   first_pos=dict(UNIFORM_POOL_FIRST_POS),
                   any_pos=dict(UNIFORM_POOL_ANY_POS),
                   def_any_share=0.05, def_first_share=0.05)


@dataclass
class History:
    """Accumulated point-in-time counts (one season, or a pool source).

    Updated game by game in chronological order; a game's own data
    is never in the history used to price it.
    """
    team_games: Counter = field(default_factory=Counter)
    team_first: Counter = field(default_factory=Counter)
    team_first_def: Counter = field(default_factory=Counter)
    player_first_off: Counter = field(default_factory=Counter)
    player_any_off: Counter = field(default_factory=Counter)
    team_any_off: Counter = field(default_factory=Counter)
    team_any_def: Counter = field(default_factory=Counter)
    games: int = 0
    no_td_games: int = 0
    first_pos_counts: Counter = field(default_factory=Counter)
    any_pos_counts: Counter = field(default_factory=Counter)
    off_first_total: int = 0
    off_any_total: int = 0
    def_first_total: int = 0
    def_any_total: int = 0

    def team_any_total(self, team: str) -> int:
        return self.team_any_off[team] + self.team_any_def[team]

    def update_game(self, *, home: str, away: str,
                    first_td: tuple | None,
                    td_credits: Sequence[tuple]) -> None:
        """Fold one finished game into the history.

        first_td: (player_id, team, td_type, pos_group) or None for a
        no-TD game. td_credits: every credited TD of the game as
        (player_id, team, td_type, pos_group).
        """
        self.games += 1
        self.team_games[home] += 1
        self.team_games[away] += 1
        if first_td is None:
            self.no_td_games += 1
        else:
            pid, team, ttype, group = first_td
            self.team_first[team] += 1
            if ttype in DEF_RETURN_TYPES:
                self.team_first_def[team] += 1
                self.def_first_total += 1
            else:
                self.player_first_off[(team, pid)] += 1
                self.first_pos_counts[group] += 1
                self.off_first_total += 1
        for pid, team, ttype, group in td_credits:
            if ttype in DEF_RETURN_TYPES:
                self.team_any_def[team] += 1
                self.def_any_total += 1
            else:
                self.player_any_off[(team, pid)] += 1
                self.team_any_off[team] += 1
                self.any_pos_counts[group] += 1
                self.off_any_total += 1

    def pools(self) -> Pools:
        if self.games == 0:
            return Pools.uniform()
        no_td_rate = self.no_td_games / self.games
        all_first = self.off_first_total + self.def_first_total
        all_any = self.off_any_total + self.def_any_total
        first_pos = {
            g: (self.first_pos_counts[g] / self.off_first_total
                if self.off_first_total else
                UNIFORM_POOL_FIRST_POS[g])
            for g in POSITION_GROUPS}
        any_pos = {
            g: (self.any_pos_counts[g] / self.off_any_total
                if self.off_any_total else UNIFORM_POOL_ANY_POS[g])
            for g in POSITION_GROUPS}
        return Pools(
            games=self.games,
            no_td_rate=no_td_rate,
            team_first_rate=(1.0 - no_td_rate) / 2.0,
            first_pos=first_pos,
            any_pos=any_pos,
            def_any_share=(self.def_any_total / all_any
                           if all_any else 0.05),
            def_first_share=(self.def_first_total / all_first
                             if all_first else 0.05),
        )


def _anytime_share(hist: History, pools: Pools, team: str,
                   pid: str, group: str) -> float:
    """Part 2-style shrunk estimate of pid's share of team's TDs."""
    n = hist.team_any_total(team)
    return (hist.player_any_off[(team, pid)]
            + K_ANYTIME * pools.any_pos[group]) / (n + K_ANYTIME)


def _anytime_def_share(hist: History, pools: Pools, team: str) -> float:
    n = hist.team_any_total(team)
    return (hist.team_any_def[team]
            + K_ANYTIME * pools.def_any_share) / (n + K_ANYTIME)


def _stage1(hist: History, pools: Pools, home: str, away: str):
    def w(team: str) -> float:
        return (hist.team_first[team]
                + K_STAGE1 * pools.team_first_rate) / (
                    hist.team_games[team] + K_STAGE1)
    wh, wa = w(home), w(away)
    z = wh + wa + pools.no_td_rate
    return wh / z, wa / z, pools.no_td_rate / z


def _renorm(weights: Mapping[str, float]) -> dict:
    z = sum(weights.values())
    if z <= 0:
        raise ValueError("NONPOSITIVE_WEIGHT_SUM")
    return {k: v / z for k, v in weights.items()}


def predict_v1(hist: History, pools: Pools, home: str, away: str,
               candidates: Mapping[str, Sequence[tuple]]) -> dict:
    """NFL_FIRST_TD_V1 distribution over the game's first TD.

    candidates: team -> [(player_id, position_group)] (the board).
    Outcome keys: 'P:<player_id>', 'DEFST:<team>', 'NO_TD'.
    """
    ph, pa, p_no = _stage1(hist, pools, home, away)
    out = {"NO_TD": p_no}
    for team, p_team in ((home, ph), (away, pa)):
        n_first = hist.team_first[team]
        weights = {}
        for pid, group in candidates.get(team, ()):
            any_p = _anytime_share(hist, pools, team, pid, group)
            weights[f"P:{pid}"] = (
                hist.player_first_off[(team, pid)] + K1_STAGE2 * any_p)
        weights[f"DEFST:{team}"] = (
            hist.team_first_def[team]
            + K1_STAGE2 * _anytime_def_share(hist, pools, team))
        shares = _renorm(weights)
        for key, share in shares.items():
            out[key] = p_team * share
    return _renorm(out)


def predict_b1(hist: History, pools: Pools, home: str, away: str,
               candidates: Mapping[str, Sequence[tuple]]) -> dict:
    """B1: anytime-share-only (stage 2 collapsed; stage 1 unchanged)."""
    ph, pa, p_no = _stage1(hist, pools, home, away)
    out = {"NO_TD": p_no}
    for team, p_team in ((home, ph), (away, pa)):
        weights = {
            f"P:{pid}": _anytime_share(hist, pools, team, pid, group)
            for pid, group in candidates.get(team, ())}
        weights[f"DEFST:{team}"] = _anytime_def_share(hist, pools, team)
        shares = _renorm(weights)
        for key, share in shares.items():
            out[key] = p_team * share
    return _renorm(out)


def predict_b2(pools: Pools, home: str, away: str,
               candidates: Mapping[str, Sequence[tuple]]) -> dict:
    """B2: league positional pool only (no team or player history)."""
    p_team = (1.0 - pools.no_td_rate) / 2.0
    out = {"NO_TD": pools.no_td_rate}
    for team in (home, away):
        group_counts = Counter(g for _, g in candidates.get(team, ()))
        weights = {
            f"P:{pid}": (pools.first_pos[group] / group_counts[group]
                         if group_counts[group] else 0.0)
            for pid, group in candidates.get(team, ())}
        weights[f"DEFST:{team}"] = pools.def_first_share
        shares = _renorm(weights)
        for key, share in shares.items():
            out[key] = p_team * share
    return _renorm(out)
