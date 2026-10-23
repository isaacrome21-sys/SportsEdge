"""NHL research-only player/goalie event layer on top of ``nhl_foundation`` paths.

RESEARCH_ONLY / NO_VALIDATION. Caller-supplied rates only (synthetic in tests);
no fitting, no backtest, no prices, not wired to RUN IT, no activation.

Conservation contract (every props path):
  * shots on goal (SOG) per skater >= that skater's goals (goals are a subset of
    SOG); team SOG == sum of skater SOG; shootout attempts are never SOG;
  * goalie saves == opponent SOG - opponent goals (empty-net goals are SOG that
    the goalie did not face and did not allow, so they cancel) and are >= 0;
  * power-play goals are a subset of the team's goals; a player's PP points ==
    PP goals scored + PP goals assisted, and team PP goals <= team goals;
  * blocks are credited to the defending team and never exceed the opponent's
    unblocked-plus-blocked attempt budget passed in; hits are nonnegative ints.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from sportsedge.research.nhl_foundation import (GamePath, NHLFoundationError, OT_MIN,
                                                TeamInput, _finite_nonneg, _ou)

STATUS = "RESEARCH_ONLY"
VALIDATION = "NO_VALIDATION"


@dataclass(frozen=True)
class TeamPropsInput:
    team_id: str
    goalie_id: str
    extra_sog_per60: dict      # skater -> non-goal SOG rate per 60
    blocks_per60: dict         # skater -> blocked shots per 60
    hits_per60: dict           # skater -> hits per 60
    pp_goal_share: float       # probability a non-empty-net goal is on the PP

    def validate(self, team: TeamInput):
        if self.team_id != team.team_id:
            raise NHLFoundationError("NHL_PROPS_TEAM_IDENTITY_MISMATCH", str(self.team_id))
        if not isinstance(self.goalie_id, str) or not self.goalie_id.strip():
            raise NHLFoundationError("NHL_GOALIE_ID_MISSING", self.team_id)
        if self.goalie_id in team.scorer_shares:
            raise NHLFoundationError("NHL_GOALIE_IS_SKATER", self.goalie_id)
        roster = set(team.scorer_shares)
        for name in ("extra_sog_per60", "blocks_per60", "hits_per60"):
            d = getattr(self, name)
            if set(d) - roster:
                raise NHLFoundationError("NHL_PROPS_PLAYER_NOT_ON_ROSTER",
                                         f"{self.team_id}.{name}")
            for pid, v in d.items():
                _finite_nonneg(f"{self.team_id}.{name}.{pid}", v)
        _finite_nonneg(f"{self.team_id}.pp_goal_share", self.pp_goal_share)
        if self.pp_goal_share > 1:
            raise NHLFoundationError("NHL_INPUT_OUT_OF_RANGE", "pp_goal_share")


@dataclass
class PropsPath:
    game: GamePath
    goalies: dict              # team_id -> goalie_id
    sog: dict                  # player -> SOG
    blocks: dict
    hits: dict
    pp_goal_index: frozenset   # indices into game.goals that were PP goals

    def team_sog(self, team, roster):
        return sum(self.sog.get(p, 0) for p in roster)


def _poisson(rng, lam):
    if lam <= 0:
        return 0
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def simulate_props(game: GamePath, home: TeamInput, away: TeamInput,
                   hp: TeamPropsInput, ap: TeamPropsInput, rng: random.Random) -> PropsPath:
    hp.validate(home)
    ap.validate(away)
    if hp.goalie_id == ap.goalie_id:
        raise NHLFoundationError("NHL_GOALIE_IDENTITY_COLLISION", hp.goalie_id)
    if not isinstance(rng, random.Random):
        raise NHLFoundationError("NHL_RNG_REQUIRED")
    minutes = 60.0 + (OT_MIN if any(g.period == 4 for g in game.goals) else 0.0)
    frac = minutes / 60.0
    sog, blocks, hits = {}, {}, {}
    for team, pin in ((home, hp), (away, ap)):
        for pid in team.scorer_shares:
            sog[pid] = game.player_goals(pid) + _poisson(rng, pin.extra_sog_per60.get(pid, 0) * frac)
            blocks[pid] = _poisson(rng, pin.blocks_per60.get(pid, 0) * frac)
            hits[pid] = _poisson(rng, pin.hits_per60.get(pid, 0) * frac)
    share = {home.team_id: hp.pp_goal_share, away.team_id: ap.pp_goal_share}
    pp = frozenset(i for i, g in enumerate(game.goals)
                   if not g.empty_net and rng.random() < share[g.team_id])
    path = PropsPath(game, {home.team_id: hp.goalie_id, away.team_id: ap.goalie_id},
                     sog, blocks, hits, pp)
    check_props(path, home, away)
    return path


def check_props(path: PropsPath, home: TeamInput, away: TeamInput):
    g = path.game
    for d, name in ((path.sog, "SOG"), (path.blocks, "BLOCKS"), (path.hits, "HITS")):
        for pid, v in d.items():
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise NHLFoundationError(f"NHL_{name}_INVALID", pid)
    rosters = {home.team_id: set(home.scorer_shares), away.team_id: set(away.scorer_shares)}
    for team, roster in rosters.items():
        if set(path.sog) & roster != roster:
            raise NHLFoundationError("NHL_SOG_MISSING_PLAYER", team)
        for pid in roster:
            if path.sog[pid] < g.player_goals(pid):
                raise NHLFoundationError("NHL_GOALS_EXCEED_SOG", pid)
    for i in path.pp_goal_index:
        if not isinstance(i, int) or not 0 <= i < len(g.goals):
            raise NHLFoundationError("NHL_PP_GOAL_UNKNOWN", str(i))
    for team in rosters:
        if goalie_saves(path, rosters, team) < 0:
            raise NHLFoundationError("NHL_NEGATIVE_SAVES", team)
    return True


def goalie_saves(path: PropsPath, rosters: dict, team: str) -> int:
    opp = path.game.away_id if team == path.game.home_id else path.game.home_id
    return path.team_sog(opp, rosters[opp]) - path.game.team_goals(opp)


def pp_points(path: PropsPath, pid: str) -> int:
    pts = 0
    for i in path.pp_goal_index:
        goal = path.game.goals[i]
        pts += (goal.scorer == pid) + (pid in goal.assists)
    return pts


def settle_prop(path: PropsPath, home: TeamInput, away: TeamInput, market: str, *,
                player_id, team_id, line):
    check_props(path, home, away)
    rosters = {home.team_id: set(home.scorer_shares), away.team_id: set(away.scorer_shares)}
    if team_id not in rosters:
        raise NHLFoundationError("NHL_TEAM_IDENTITY_MISMATCH", str(team_id))
    if market == "GOALIE_SAVES":
        if player_id != path.goalies[team_id]:
            raise NHLFoundationError("NHL_GOALIE_IDENTITY_MISMATCH", str(player_id))
        return _ou(goalie_saves(path, rosters, team_id), line)
    if player_id not in rosters[team_id]:
        raise NHLFoundationError("NHL_PLAYER_IDENTITY_MISMATCH", str(player_id))
    value = {"PLAYER_SHOTS": lambda: path.sog[player_id],
             "PLAYER_BLOCKS": lambda: path.blocks[player_id],
             "PLAYER_HITS": lambda: path.hits[player_id],
             "POWER_PLAY_POINTS": lambda: pp_points(path, player_id)}.get(market)
    if value is None:
        raise NHLFoundationError("NHL_MARKET_NO_SETTLEMENT", market)
    return _ou(value(), line)


PROPS_MARKETS = frozenset({"PLAYER_SHOTS", "GOALIE_SAVES", "PLAYER_BLOCKS",
                           "PLAYER_HITS", "POWER_PLAY_POINTS"})
