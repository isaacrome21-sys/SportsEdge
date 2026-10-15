"""NHL research-only foundation: coherent joint game path + settlement + terminal map.

RESEARCH_ONLY / NO_VALIDATION. Nothing in this module is fitted to real data,
validated, or wired to the canonical RUN IT path. Inputs are caller-supplied
rates (synthetic in tests); the module never invents odds or probabilities for
a live market. No collectors, no paid APIs, no activation.

Coherence contract (every simulated path):
  * every goal has exactly one scorer on the scoring team and 0-2 distinct
    assisters on the same team, none equal to the scorer;
  * team regulation+OT goals == sum of that team's player goals;
  * period goals sum to the regulation/OT totals;
  * a shootout awards the winner exactly one "decisive goal" for final-score
    settlement but credits NO player goal/point and no period goal;
  * empty-net goals are flagged and only occur in P3 (regulation).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

STATUS = "RESEARCH_ONLY"
VALIDATION = "NO_VALIDATION"

TERMINALS = frozenset({
    "VERIFIED_EDGE_ELIGIBLE", "VALIDATED_FOR_FORWARD", "RESEARCH_ONLY",
    "NO_VALIDATION", "NO_ENGINE", "NO_DATA", "NO_QUOTE", "NO_SETTLEMENT",
    "NOT_OFFERED", "BLOCKED_BY_AUTHORIZATION",
})
# Terminals this research module may ever assign. Validation-level terminals
# require a separate governance ruling and are deliberately unreachable here.
_ALLOWED = TERMINALS - {"VERIFIED_EDGE_ELIGIBLE", "VALIDATED_FOR_FORWARD"}

REG_PERIOD_MIN = 20.0
OT_MIN = 5.0


class NHLFoundationError(ValueError):
    """Fail-closed refusal with a named reason code."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def _finite_nonneg(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NHLFoundationError("NHL_INPUT_NOT_NUMERIC", name)
    if not math.isfinite(value):
        raise NHLFoundationError("NHL_INPUT_NONFINITE", name)
    if value < 0:
        raise NHLFoundationError("NHL_INPUT_NEGATIVE", name)
    return float(value)


@dataclass(frozen=True)
class TeamInput:
    team_id: str
    goals_per_60: float
    scorer_shares: dict          # player_id -> share of team goals (sum == 1)
    assist_shares: dict          # player_id -> assist weight (>= 0)
    empty_net_goals_per_60: float = 0.0   # rate while opponent net is empty

    def validate(self):
        if not isinstance(self.team_id, str) or not self.team_id.strip():
            raise NHLFoundationError("NHL_TEAM_ID_MISSING")
        _finite_nonneg(f"{self.team_id}.goals_per_60", self.goals_per_60)
        _finite_nonneg(f"{self.team_id}.empty_net_goals_per_60",
                       self.empty_net_goals_per_60)
        if not self.scorer_shares:
            raise NHLFoundationError("NHL_SCORER_SHARES_EMPTY", self.team_id)
        for pid, s in {**self.scorer_shares, **self.assist_shares}.items():
            if not isinstance(pid, str) or not pid.strip():
                raise NHLFoundationError("NHL_PLAYER_ID_MISSING", self.team_id)
            _finite_nonneg(f"{self.team_id}.{pid}", s)
        total = sum(self.scorer_shares.values())
        if abs(total - 1.0) > 1e-9:
            raise NHLFoundationError("NHL_SCORER_SHARES_NOT_NORMALIZED",
                                     f"{self.team_id} sum={total}")
        if set(self.assist_shares) - set(self.scorer_shares):
            raise NHLFoundationError("NHL_ASSIST_PLAYER_NOT_ON_ROSTER",
                                     self.team_id)


@dataclass(frozen=True)
class Goal:
    team_id: str
    period: int            # 1..3 regulation, 4 = OT
    minute: float
    scorer: str
    assists: tuple
    empty_net: bool = False


@dataclass
class GamePath:
    home_id: str
    away_id: str
    goals: list = field(default_factory=list)
    shootout_winner: str | None = None

    def team_goals(self, team_id, *, periods=None):
        return sum(1 for g in self.goals if g.team_id == team_id
                   and (periods is None or g.period in periods))

    def final_score(self):
        """Settlement score: shootout winner credited one decisive goal."""
        h = self.team_goals(self.home_id)
        a = self.team_goals(self.away_id)
        if self.shootout_winner == self.home_id:
            h += 1
        elif self.shootout_winner == self.away_id:
            a += 1
        return h, a

    def player_goals(self, pid):
        return sum(1 for g in self.goals if g.scorer == pid)

    def player_assists(self, pid):
        return sum(1 for g in self.goals if pid in g.assists)

    def player_points(self, pid):
        return self.player_goals(pid) + self.player_assists(pid)


def _weighted(rng, weights: dict, exclude=()):
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


def _goal(rng, team: TeamInput, period, minute, empty_net=False):
    scorer = _weighted(rng, team.scorer_shares)
    assists = []
    for _ in range(2):
        if rng.random() < 0.8 - 0.3 * len(assists):
            a = _weighted(rng, team.assist_shares, exclude=(scorer, *assists))
            if a is None:
                break
            assists.append(a)
    return Goal(team.team_id, period, minute, scorer, tuple(assists), empty_net)


def simulate_game(home: TeamInput, away: TeamInput, rng: random.Random, *,
                  allow_shootout: bool = True,
                  pull_window_min: float = 2.0) -> GamePath:
    """One coherent game path (regular-season rules: 5-min 3v3 OT, then SO)."""
    home.validate()
    away.validate()
    if home.team_id == away.team_id:
        raise NHLFoundationError("NHL_TEAM_IDENTITY_COLLISION", home.team_id)
    overlap = set(home.scorer_shares) & set(away.scorer_shares)
    if overlap:
        raise NHLFoundationError("NHL_PLAYER_ON_BOTH_TEAMS", sorted(overlap)[0])
    if not isinstance(rng, random.Random):
        raise NHLFoundationError("NHL_RNG_REQUIRED")
    _finite_nonneg("pull_window_min", pull_window_min)
    path = GamePath(home.team_id, away.team_id)
    teams = (home, away)

    def run_segment(period, start, end, sudden_death):
        t = start
        rates = [x.goals_per_60 / 60.0 for x in teams]
        total = sum(rates)
        while total > 0:
            t += rng.expovariate(total)
            if t >= end:
                return
            i = 0 if rng.random() * total < rates[0] else 1
            path.goals.append(_goal(rng, teams[i], period, t))
            if sudden_death:
                return

    for p in (1, 2):
        run_segment(p, 0.0, REG_PERIOD_MIN, False)
    pull = REG_PERIOD_MIN - pull_window_min
    run_segment(3, 0.0, pull, False)
    # Final window: a team trailing by 1-2 pulls its goalie.
    diff = path.team_goals(home.team_id) - path.team_goals(away.team_id)
    if diff in (1, 2, -1, -2):
        leader, trailer = (home, away) if diff > 0 else (away, home)
        t = pull
        rates = [leader.empty_net_goals_per_60 / 60.0,
                 trailer.goals_per_60 * 1.5 / 60.0]
        total = sum(rates)
        while total > 0:
            t += rng.expovariate(total)
            if t >= REG_PERIOD_MIN:
                break
            if rng.random() * total < rates[0]:
                path.goals.append(_goal(rng, leader, 3, t, empty_net=True))
            else:
                path.goals.append(_goal(rng, trailer, 3, t))
            d = path.team_goals(home.team_id) - path.team_goals(away.team_id)
            if d == 0 or abs(d) > 2:
                break
        if t < REG_PERIOD_MIN:
            run_segment(3, t, REG_PERIOD_MIN, False)
    else:
        run_segment(3, pull, REG_PERIOD_MIN, False)
    if path.team_goals(home.team_id) == path.team_goals(away.team_id):
        run_segment(4, 0.0, OT_MIN, True)
        if path.team_goals(home.team_id) == path.team_goals(away.team_id):
            if not allow_shootout:
                raise NHLFoundationError("NHL_PLAYOFF_OT_NOT_MODELED")
            path.shootout_winner = home.team_id if rng.random() < 0.5 else away.team_id
    check_path(path, home, away)
    return path


def check_path(path: GamePath, home: TeamInput, away: TeamInput):
    """Raise on any conservation or impossible-event violation."""
    rosters = {home.team_id: set(home.scorer_shares),
               away.team_id: set(away.scorer_shares)}
    if {path.home_id, path.away_id} != set(rosters):
        raise NHLFoundationError("NHL_PATH_TEAM_MISMATCH")
    ot_goals = 0
    for g in path.goals:
        if g.team_id not in rosters:
            raise NHLFoundationError("NHL_GOAL_UNKNOWN_TEAM", g.team_id)
        if g.scorer not in rosters[g.team_id]:
            raise NHLFoundationError("NHL_SCORER_NOT_ON_TEAM", g.scorer)
        if len(g.assists) > 2 or len(set(g.assists)) != len(g.assists) \
                or g.scorer in g.assists:
            raise NHLFoundationError("NHL_ASSIST_INVALID", g.scorer)
        if any(a not in rosters[g.team_id] for a in g.assists):
            raise NHLFoundationError("NHL_ASSIST_NOT_ON_TEAM", g.scorer)
        if g.period not in (1, 2, 3, 4):
            raise NHLFoundationError("NHL_PERIOD_INVALID", str(g.period))
        lim = OT_MIN if g.period == 4 else REG_PERIOD_MIN
        if not (math.isfinite(g.minute) and 0 <= g.minute < lim):
            raise NHLFoundationError("NHL_GOAL_TIME_INVALID", str(g.minute))
        if g.empty_net and g.period != 3:
            raise NHLFoundationError("NHL_EMPTY_NET_OUTSIDE_P3")
        ot_goals += g.period == 4
    if ot_goals > 1:
        raise NHLFoundationError("NHL_OT_NOT_SUDDEN_DEATH")
    reg_h = path.team_goals(path.home_id, periods=(1, 2, 3))
    reg_a = path.team_goals(path.away_id, periods=(1, 2, 3))
    if ot_goals and reg_h != reg_a:
        raise NHLFoundationError("NHL_OT_AFTER_DECIDED_REGULATION")
    if path.shootout_winner is not None:
        if path.shootout_winner not in rosters:
            raise NHLFoundationError("NHL_SHOOTOUT_WINNER_UNKNOWN")
        if ot_goals or reg_h != reg_a:
            raise NHLFoundationError("NHL_SHOOTOUT_AFTER_DECIDED_GAME")
    elif reg_h == reg_a and not ot_goals:
        raise NHLFoundationError("NHL_GAME_ENDED_TIED")
    for tid in rosters:
        if path.team_goals(tid) != sum(path.player_goals(p) for p in rosters[tid]):
            raise NHLFoundationError("NHL_PLAYER_TEAM_GOALS_MISMATCH", tid)
    return True


# --- settlement ---------------------------------------------------------
def _ou(value, line):
    if not (isinstance(line, (int, float)) and not isinstance(line, bool)
            and math.isfinite(line)):
        raise NHLFoundationError("NHL_LINE_NONFINITE", repr(line))
    if value > line:
        return "OVER"
    if value < line:
        return "UNDER"
    return "PUSH"


def settle(path: GamePath, market: str, *, selection=None, line=None,
           period=None, player_id=None):
    """Settle a market on a path. Returns WIN/LOSE/PUSH or OVER/UNDER/PUSH."""
    h, a = path.final_score()
    if market == "MONEYLINE":            # includes OT and shootout
        if selection not in (path.home_id, path.away_id):
            raise NHLFoundationError("NHL_SELECTION_IDENTITY_MISMATCH", str(selection))
        winner = path.home_id if h > a else path.away_id
        return "WIN" if selection == winner else "LOSE"
    if market == "REGULATION_3WAY":       # 60 minutes only
        rh = path.team_goals(path.home_id, periods=(1, 2, 3))
        ra = path.team_goals(path.away_id, periods=(1, 2, 3))
        res = "DRAW" if rh == ra else (path.home_id if rh > ra else path.away_id)
        if selection not in (path.home_id, path.away_id, "DRAW"):
            raise NHLFoundationError("NHL_SELECTION_IDENTITY_MISMATCH", str(selection))
        return "WIN" if selection == res else "LOSE"
    if market == "PUCK_LINE":             # final score incl. SO decisive goal
        if selection not in (path.home_id, path.away_id):
            raise NHLFoundationError("NHL_SELECTION_IDENTITY_MISMATCH", str(selection))
        margin = (h - a) if selection == path.home_id else (a - h)
        r = _ou(margin + line, 0)
        return {"OVER": "WIN", "UNDER": "LOSE", "PUSH": "PUSH"}[r]
    if market == "TOTAL":                 # incl. OT goal and SO decisive goal
        return _ou(h + a, line)
    if market == "TEAM_TOTAL":
        if selection not in (path.home_id, path.away_id):
            raise NHLFoundationError("NHL_SELECTION_IDENTITY_MISMATCH", str(selection))
        return _ou(h if selection == path.home_id else a, line)
    if market == "PERIOD_TOTAL":
        if period not in (1, 2, 3):
            raise NHLFoundationError("NHL_PERIOD_INVALID", str(period))
        return _ou(sum(1 for g in path.goals if g.period == period), line)
    if market in ("PLAYER_GOALS", "PLAYER_ASSISTS", "PLAYER_POINTS"):
        if not isinstance(player_id, str) or not player_id:
            raise NHLFoundationError("NHL_PLAYER_ID_MISSING")
        fn = {"PLAYER_GOALS": path.player_goals, "PLAYER_ASSISTS": path.player_assists,
              "PLAYER_POINTS": path.player_points}[market]
        return _ou(fn(player_id), line)   # shootout goals never count
    if market == "EMPTY_NET_GOAL":
        has = any(g.empty_net for g in path.goals)
        if selection not in ("YES", "NO"):
            raise NHLFoundationError("NHL_SELECTION_IDENTITY_MISMATCH", str(selection))
        return "WIN" if (selection == "YES") == has else "LOSE"
    if market == "GOES_TO_OT":
        went = path.team_goals(path.home_id, periods=(1, 2, 3)) == \
            path.team_goals(path.away_id, periods=(1, 2, 3))
        if selection not in ("YES", "NO"):
            raise NHLFoundationError("NHL_SELECTION_IDENTITY_MISMATCH", str(selection))
        return "WIN" if (selection == "YES") == went else "LOSE"
    raise NHLFoundationError("NHL_MARKET_NO_SETTLEMENT", market)


def settle_player_prop(path, home: TeamInput, away: TeamInput, market, player_id,
                       line, team_id):
    """Player prop with roster identity binding (player must be on team_id)."""
    rosters = {home.team_id: home.scorer_shares, away.team_id: away.scorer_shares}
    if team_id not in rosters:
        raise NHLFoundationError("NHL_TEAM_IDENTITY_MISMATCH", str(team_id))
    if player_id not in rosters[team_id]:
        raise NHLFoundationError("NHL_PLAYER_IDENTITY_MISMATCH", str(player_id))
    return settle(path, market, player_id=player_id, line=line)


# --- market-terminal map -------------------------------------------------
_SIM = "simulation skeleton + settlement only; no fitted rates, no backtest"
MARKET_TERMINALS = {
    "MONEYLINE": ("RESEARCH_ONLY", _SIM),
    "REGULATION_3WAY": ("RESEARCH_ONLY", _SIM),
    "PUCK_LINE": ("RESEARCH_ONLY", _SIM),
    "TOTAL": ("RESEARCH_ONLY", _SIM),
    "TEAM_TOTAL": ("RESEARCH_ONLY", _SIM),
    "PERIOD_TOTAL": ("RESEARCH_ONLY", _SIM),
    "GOES_TO_OT": ("RESEARCH_ONLY", _SIM),
    "EMPTY_NET_GOAL": ("RESEARCH_ONLY", _SIM + "; pull model is a placeholder"),
    "PLAYER_GOALS": ("RESEARCH_ONLY", _SIM),
    "PLAYER_ASSISTS": ("RESEARCH_ONLY", _SIM),
    "PLAYER_POINTS": ("RESEARCH_ONLY", _SIM),
    "PERIOD_MONEYLINE": ("NO_SETTLEMENT", "period 3-way settlement not implemented here"),
    "PLAYER_SHOTS": ("NO_ENGINE", "no shot process in this skeleton"),
    "GOALIE_SAVES": ("NO_ENGINE", "no shot/save process in this skeleton"),
    "PLAYER_BLOCKS": ("NO_ENGINE", "no block process"),
    "PLAYER_HITS": ("NO_ENGINE", "no hit process"),
    "PLAYER_PIM": ("NO_ENGINE", "no penalty process"),
    "POWER_PLAY_POINTS": ("NO_ENGINE", "no manpower-state process"),
    "FIRST_GOAL_SCORER": ("NO_SETTLEMENT", "first-goal settlement rules not encoded"),
    "SHOOTOUT_PROPS": ("NO_ENGINE", "shootout is a coin-flip placeholder"),
    "CORRECT_SCORE": ("NO_SETTLEMENT", "correct-score settlement not encoded"),
    "PLAYOFF_SERIES": ("NO_ENGINE", "playoff OT and series paths not modeled"),
}
for _m, (_t, _r) in MARKET_TERMINALS.items():
    assert _t in _ALLOWED, (_m, _t)


def market_terminal(market: str):
    """Exactly one terminal per market; unknown markets are NO_ENGINE."""
    t, reason = MARKET_TERMINALS.get(market, ("NO_ENGINE", "market not inventoried"))
    return {"sport": "NHL", "market": market, "terminal": t, "reason": reason,
            "validation": VALIDATION, "probability": None, "price": None, "ev": None}
