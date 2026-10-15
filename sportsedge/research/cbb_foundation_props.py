"""CBB research-only box-score layer on top of ``cbb_foundation`` paths.

RESEARCH_ONLY / NO_VALIDATION. Caller-supplied rates only (synthetic in tests);
no fitting, no backtest, no prices, not wired to RUN IT, no activation.

Conservation contract (every props path):
  * every rebound record answers exactly one live missed shot; for each team,
    offensive rebounds + opponent defensive rebounds + team rebounds on its
    misses == its live misses, and live misses <= missed FG + missed FT;
  * an assist only exists on a made FG2/FG3 (never a FT), at most one per make,
    credited to a teammate of the scorer who is not the scorer;
  * a steal answers exactly one opponent turnover (steals <= opponent TOV);
  * a block answers exactly one opponent missed FG (blocks <= opponent misses);
  * combos (PRA/PR/PA/RA) are sums of the same per-player counts; a double-double
    is >= 10 in at least two of points/rebounds/assists/steals/blocks;
  * race-to-N uses an explicit within-period timeline of the same made shots,
    so the race winner always has >= N points at the end.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from sportsedge.research.cbb_foundation import (EVENT_POINTS, OT_MIN, REG_PERIOD_MIN,
                                                REG_PERIODS, SPORT, FoundationError,
                                                GamePath, TeamInput, _num, _ou)

STATUS = "RESEARCH_ONLY"
VALIDATION = "NO_VALIDATION"
RATE_MIN = 40.0
LIVE_FT_MISS_SHARE = 0.45   # placeholder share of FT misses that are live balls
CATEGORIES = ("PTS", "REB", "AST", "STL", "BLK")


@dataclass(frozen=True)
class PlayerPropsInput:
    miss_fg2_per40: float = 0.0
    miss_fg3_per40: float = 0.0
    miss_ft_per40: float = 0.0
    tov_per40: float = 0.0
    oreb_w: float = 1.0
    dreb_w: float = 1.0
    ast_w: float = 1.0
    stl_w: float = 1.0
    blk_w: float = 1.0


@dataclass(frozen=True)
class TeamPropsInput:
    team_id: str
    players: dict                 # player_id -> PlayerPropsInput
    assist_rate: float = 0.6
    oreb_rate: float = 0.25
    steal_rate: float = 0.5
    block_rate: float = 0.08
    team_reb_rate: float = 0.05

    def validate(self, team: TeamInput):
        if self.team_id != team.team_id:
            raise FoundationError(f"{SPORT}_PROPS_TEAM_IDENTITY_MISMATCH", str(self.team_id))
        if set(self.players) != team.roster:
            raise FoundationError(f"{SPORT}_PROPS_ROSTER_MISMATCH", self.team_id)
        for k in ("assist_rate", "oreb_rate", "steal_rate", "block_rate", "team_reb_rate"):
            v = _num(f"{self.team_id}.{k}", getattr(self, k))
            if v > 1:
                raise FoundationError(f"{SPORT}_INPUT_OUT_OF_RANGE", k)
        for pid, p in self.players.items():
            for k in PlayerPropsInput.__dataclass_fields__:
                _num(f"{pid}.{k}", getattr(p, k))


@dataclass
class PropsPath:
    game: GamePath
    rosters: dict                                 # team -> frozenset(players)
    misses: dict = field(default_factory=dict)     # (pid, kind) -> count; kind FG2/FG3/FT
    live_misses: dict = field(default_factory=dict)   # team -> live misses
    rebounds: list = field(default_factory=list)  # (miss_team, reb_team, pid | "TEAM")
    assists: list = field(default_factory=list)   # (event_index, assister)
    turnovers: dict = field(default_factory=dict)  # pid -> count
    steals: list = field(default_factory=list)    # (victim_pid, stealer_pid)
    blocks: list = field(default_factory=list)    # (shooter_pid, blocker_pid)
    timeline: list = field(default_factory=list)  # event indices in time order

    def team_of(self, pid):
        for t, r in self.rosters.items():
            if pid in r:
                return t
        return None

    def stat(self, pid, cat):
        if cat == "PTS":
            return self.game.player_points(pid)
        if cat == "REB":
            return sum(1 for r in self.rebounds if r[2] == pid)
        if cat == "AST":
            return sum(1 for a in self.assists if a[1] == pid)
        if cat == "STL":
            return sum(1 for s in self.steals if s[1] == pid)
        if cat == "BLK":
            return sum(1 for b in self.blocks if b[1] == pid)
        if cat == "TOV":
            return self.turnovers.get(pid, 0)
        raise FoundationError(f"{SPORT}_STAT_UNKNOWN", cat)


def _poisson(rng, lam):
    if lam <= 0:
        return 0
    if lam > 60:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def _pick(rng, weights: dict, exclude=()):
    items = [(k, w) for k, w in sorted(weights.items()) if k not in exclude and w > 0]
    tot = sum(w for _, w in items)
    if tot <= 0:
        return None
    r = rng.random() * tot
    for k, w in items:
        r -= w
        if r <= 0:
            return k
    return items[-1][0]


def simulate_props(game: GamePath, home: TeamInput, away: TeamInput,
                   hp: TeamPropsInput, ap: TeamPropsInput, rng: random.Random) -> PropsPath:
    home.validate()
    away.validate()
    hp.validate(home)
    ap.validate(away)
    if not isinstance(rng, random.Random):
        raise FoundationError(f"{SPORT}_RNG_REQUIRED")
    minutes = REG_PERIODS * REG_PERIOD_MIN + OT_MIN * (game.periods_played - REG_PERIODS)
    frac = minutes / RATE_MIN
    pin = {home.team_id: hp, away.team_id: ap}
    opp = {home.team_id: away.team_id, away.team_id: home.team_id}
    path = PropsPath(game, {home.team_id: frozenset(home.roster),
                            away.team_id: frozenset(away.roster)})
    for t, tp in pin.items():
        live = 0
        for pid, p in sorted(tp.players.items()):
            for kind, rate in (("FG2", p.miss_fg2_per40), ("FG3", p.miss_fg3_per40),
                               ("FT", p.miss_ft_per40)):
                n = _poisson(rng, rate * frac)
                path.misses[(pid, kind)] = n
                if kind == "FT":
                    live += sum(1 for _ in range(n) if rng.random() < LIVE_FT_MISS_SHARE)
                else:
                    live += n
                    ob = pin[opp[t]]
                    for _ in range(n):
                        if rng.random() < ob.block_rate:
                            b = _pick(rng, {q: x.blk_w for q, x in ob.players.items()})
                            if b is not None:
                                path.blocks.append((pid, b))
            path.turnovers[pid] = _poisson(rng, p.tov_per40 * frac)
        path.live_misses[t] = live
        for _ in range(live):
            if rng.random() < tp.team_reb_rate:
                reb_team = t if rng.random() < tp.oreb_rate else opp[t]
                path.rebounds.append((t, reb_team, "TEAM"))
                continue
            if rng.random() < tp.oreb_rate:
                who = _pick(rng, {q: x.oreb_w for q, x in tp.players.items()})
                path.rebounds.append((t, t, who) if who else (t, t, "TEAM"))
            else:
                op = pin[opp[t]]
                who = _pick(rng, {q: x.dreb_w for q, x in op.players.items()})
                path.rebounds.append((t, opp[t], who) if who else (t, opp[t], "TEAM"))
        for pid in sorted(tp.players):
            op = pin[opp[t]]
            for _ in range(path.turnovers[pid]):
                if rng.random() < op.steal_rate:
                    s = _pick(rng, {q: x.stl_w for q, x in op.players.items()})
                    if s is not None:
                        path.steals.append((pid, s))
    for i, e in enumerate(game.events):
        if e.kind in ("FG2", "FG3") and rng.random() < pin[e.team_id].assist_rate:
            a = _pick(rng, {q: x.ast_w for q, x in pin[e.team_id].players.items()},
                      exclude=(e.player_id,))
            if a is not None:
                path.assists.append((i, a))
    stamped = [(e.period + rng.random(), i) for i, e in enumerate(game.events)]
    path.timeline = [i for _, i in sorted(stamped)]
    check_props(path)
    return path


def check_props(path: PropsPath):
    g = path.game
    teams = (g.home_id, g.away_id)
    if set(path.rosters) != set(teams):
        raise FoundationError(f"{SPORT}_PROPS_TEAM_IDENTITY_MISMATCH")
    other = {teams[0]: teams[1], teams[1]: teams[0]}
    for (pid, kind), n in path.misses.items():
        if path.team_of(pid) is None or kind not in EVENT_POINTS:
            raise FoundationError(f"{SPORT}_MISS_IDENTITY_INVALID", str(pid))
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise FoundationError(f"{SPORT}_MISS_COUNT_INVALID", str(pid))
    for t in teams:
        missed = sum(n for (p, k), n in path.misses.items() if path.team_of(p) == t)
        live = path.live_misses.get(t)
        if isinstance(live, bool) or not isinstance(live, int) or not 0 <= live <= missed:
            raise FoundationError(f"{SPORT}_LIVE_MISSES_INVALID", t)
        recs = [r for r in path.rebounds if r[0] == t]
        if len(recs) != live:
            raise FoundationError(f"{SPORT}_REBOUNDS_NOT_CONSERVED", t)
        for miss_team, reb_team, who in recs:
            if reb_team not in (t, other[t]):
                raise FoundationError(f"{SPORT}_REBOUND_TEAM_INVALID", str(reb_team))
            if who != "TEAM" and who not in path.rosters[reb_team]:
                raise FoundationError(f"{SPORT}_REBOUNDER_NOT_ON_TEAM", str(who))
    seen = set()
    for i, a in path.assists:
        if not isinstance(i, int) or not 0 <= i < len(g.events) or i in seen:
            raise FoundationError(f"{SPORT}_ASSIST_EVENT_INVALID", str(i))
        seen.add(i)
        e = g.events[i]
        if e.kind not in ("FG2", "FG3"):
            raise FoundationError(f"{SPORT}_ASSIST_ON_NON_FG", e.kind)
        if a == e.player_id or a not in path.rosters[e.team_id]:
            raise FoundationError(f"{SPORT}_ASSIST_NOT_BY_TEAMMATE", str(a))
    for pid, n in path.turnovers.items():
        if path.team_of(pid) is None or isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise FoundationError(f"{SPORT}_TURNOVER_INVALID", str(pid))
    for victim, stealer in path.steals:
        vt, st = path.team_of(victim), path.team_of(stealer)
        if vt is None or st is None or vt == st:
            raise FoundationError(f"{SPORT}_STEAL_IDENTITY_INVALID", str(stealer))
    for pid in {v for v, _ in path.steals}:
        if sum(1 for v, _ in path.steals if v == pid) > path.turnovers.get(pid, 0):
            raise FoundationError(f"{SPORT}_STEALS_EXCEED_TURNOVERS", pid)
    for shooter, blocker in path.blocks:
        a, b = path.team_of(shooter), path.team_of(blocker)
        if a is None or b is None or a == b:
            raise FoundationError(f"{SPORT}_BLOCK_IDENTITY_INVALID", str(blocker))
    for pid in {s for s, _ in path.blocks}:
        fg_miss = path.misses.get((pid, "FG2"), 0) + path.misses.get((pid, "FG3"), 0)
        if sum(1 for s, _ in path.blocks if s == pid) > fg_miss:
            raise FoundationError(f"{SPORT}_BLOCKS_EXCEED_MISSES", pid)
    if sorted(path.timeline) != list(range(len(g.events))):
        raise FoundationError(f"{SPORT}_TIMELINE_INVALID")
    periods = [g.events[i].period for i in path.timeline]
    if periods != sorted(periods):
        raise FoundationError(f"{SPORT}_TIMELINE_PERIOD_ORDER")
    return True


def race_winner(path: PropsPath, n: int):
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise FoundationError(f"{SPORT}_RACE_TARGET_INVALID", repr(n))
    score = {t: 0 for t in path.rosters}
    for i in path.timeline:
        e = path.game.events[i]
        score[e.team_id] += EVENT_POINTS[e.kind]
        if score[e.team_id] >= n:
            return e.team_id
    return None


COMBOS = {"PLAYER_PRA": ("PTS", "REB", "AST"), "PLAYER_PR": ("PTS", "REB"),
          "PLAYER_PA": ("PTS", "AST"), "PLAYER_RA": ("REB", "AST"),
          "PLAYER_REBOUNDS": ("REB",), "PLAYER_ASSISTS": ("AST",),
          "PLAYER_STEALS": ("STL",), "PLAYER_BLOCKS": ("BLK",),
          "PLAYER_STEALS_BLOCKS": ("STL", "BLK"), "PLAYER_TURNOVERS": ("TOV",)}
PROPS_MARKETS = frozenset(COMBOS) | {"DOUBLE_DOUBLE", "RACE_TO_POINTS"}


def double_double(path: PropsPath, pid: str) -> bool:
    return sum(1 for c in CATEGORIES if path.stat(pid, c) >= 10) >= 2


def settle_prop(path: PropsPath, market: str, *, player_id=None, team_id=None,
                line=None, selection=None, n=None):
    """O/U for counting props; WIN/LOSE for DD; race: VOID if neither team reaches n."""
    check_props(path)
    if market == "RACE_TO_POINTS":
        if selection not in path.rosters:
            raise FoundationError(f"{SPORT}_SELECTION_IDENTITY_MISMATCH", str(selection))
        w = race_winner(path, n)
        return "VOID" if w is None else ("WIN" if w == selection else "LOSE")
    if team_id not in path.rosters:
        raise FoundationError(f"{SPORT}_TEAM_IDENTITY_MISMATCH", str(team_id))
    if player_id not in path.rosters[team_id]:
        raise FoundationError(f"{SPORT}_PLAYER_IDENTITY_MISMATCH", str(player_id))
    if market == "DOUBLE_DOUBLE":
        if selection not in ("YES", "NO"):
            raise FoundationError(f"{SPORT}_SELECTION_IDENTITY_MISMATCH", str(selection))
        return "WIN" if (selection == "YES") == double_double(path, player_id) else "LOSE"
    if market not in COMBOS:
        raise FoundationError(f"{SPORT}_MARKET_NO_SETTLEMENT", market)
    return _ou(sum(path.stat(player_id, c) for c in COMBOS[market]), line)
