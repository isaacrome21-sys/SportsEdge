"""CBB (men's college basketball) research-only foundation: coherent joint box-score path + settlement + terminal map.

RESEARCH_ONLY / NO_VALIDATION. Not fitted to real data, not validated, not wired
to the canonical RUN IT path, no odds or probabilities for live markets.

Coherence contract (every simulated path):
  * each scoring event belongs to one player on one team (2PT, 3PT or FT);
  * player points == 2*FG2 + 3*FG3 + FT; team points == sum of player points;
  * two 20-minute halves sum to regulation; OT periods (5 min) are appended only
    while tied, and the game never ends tied;
  * settlement: moneyline, spread, total, team total and player props include
    OT; 1H excludes OT; 2H includes OT.
  * Owner exclusion: no Illinois college team may be simulated, settled or
    carried on a card. Any Illinois school (name list or frozen ESPN-id registry
    in ``artifacts.free_models``) yields BLOCKED_BY_AUTHORIZATION /
    ILLINOIS_COLLEGE_EXCLUDED before any other work.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

STATUS = "RESEARCH_ONLY"
VALIDATION = "NO_VALIDATION"
SPORT = "CBB"
TERMINALS = frozenset({
    "VERIFIED_EDGE_ELIGIBLE", "VALIDATED_FOR_FORWARD", "RESEARCH_ONLY",
    "NO_VALIDATION", "NO_ENGINE", "NO_DATA", "NO_QUOTE", "NO_SETTLEMENT",
    "NOT_OFFERED", "BLOCKED_BY_AUTHORIZATION",
})
_ALLOWED = TERMINALS - {"VERIFIED_EDGE_ELIGIBLE", "VALIDATED_FOR_FORWARD"}
REG_PERIODS = 2          # halves
REG_PERIOD_MIN = 20.0
OT_MIN = 5.0
MAX_OT = 10              # refuse rather than loop forever on degenerate input
EVENT_POINTS = {"FG2": 2, "FG3": 3, "FT": 1}


def _norm(name):
    return " ".join(str(name).lower().replace(".", " ").replace("-", " ").split())


def _excluded_keys():
    from artifacts.free_models import IL_COLLEGE_ESPN_IDS, IL_COLLEGE_NAMES
    names = {_norm(n) for n in IL_COLLEGE_NAMES}
    names |= {_norm(n) for n in IL_COLLEGE_ESPN_IDS.values()}
    return names, {str(k) for k in IL_COLLEGE_ESPN_IDS}


def illinois_excluded(*identities) -> bool:
    """True when any team name or ESPN id is an Illinois college (fail closed)."""
    names, ids = _excluded_keys()
    for ident in identities:
        if ident is None:
            continue
        if str(ident).strip() in ids or _norm(ident) in names:
            return True
    return False


class FoundationError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def _num(name, v, *, positive=False):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise FoundationError(f"{SPORT}_INPUT_NOT_NUMERIC", name)
    if not math.isfinite(v):
        raise FoundationError(f"{SPORT}_INPUT_NONFINITE", name)
    if v < 0 or (positive and v == 0):
        raise FoundationError(f"{SPORT}_INPUT_NEGATIVE", name)
    return float(v)


@dataclass(frozen=True)
class PlayerInput:
    player_id: str
    # expected scoring events per 40 team-minutes while the team plays
    fg2_per40: float
    fg3_per40: float
    ft_per40: float


@dataclass(frozen=True)
class TeamInput:
    team_id: str
    players: tuple            # tuple[PlayerInput]
    espn_id: str | None = None
    display_name: str | None = None

    def validate(self):
        if illinois_excluded(self.team_id, self.espn_id, self.display_name):
            raise FoundationError("ILLINOIS_COLLEGE_EXCLUDED", str(self.team_id))
        if not isinstance(self.team_id, str) or not self.team_id.strip():
            raise FoundationError(f"{SPORT}_TEAM_ID_MISSING")
        if not self.players:
            raise FoundationError(f"{SPORT}_ROSTER_EMPTY", self.team_id)
        ids = [p.player_id for p in self.players]
        if any(not isinstance(i, str) or not i.strip() for i in ids):
            raise FoundationError(f"{SPORT}_PLAYER_ID_MISSING", self.team_id)
        if len(set(ids)) != len(ids):
            raise FoundationError(f"{SPORT}_PLAYER_DUPLICATE", self.team_id)
        for p in self.players:
            for k in ("fg2_per40", "fg3_per40", "ft_per40"):
                _num(f"{p.player_id}.{k}", getattr(p, k))

    @property
    def roster(self):
        return {p.player_id for p in self.players}


@dataclass(frozen=True)
class Event:
    team_id: str
    player_id: str
    period: int        # 1..4 regulation, 5+ OT
    kind: str          # FG2 / FG3 / FT


@dataclass
class GamePath:
    home_id: str
    away_id: str
    events: list = field(default_factory=list)
    periods_played: int = REG_PERIODS

    def points(self, team_id, periods=None):
        return sum(EVENT_POINTS[e.kind] for e in self.events if e.team_id == team_id
                   and (periods is None or e.period in periods))

    def player_points(self, pid):
        return sum(EVENT_POINTS[e.kind] for e in self.events if e.player_id == pid)

    def player_count(self, pid, kind):
        return sum(1 for e in self.events if e.player_id == pid and e.kind == kind)

    def final_score(self):
        return self.points(self.home_id), self.points(self.away_id)


def _poisson(rng, lam):
    # Knuth for small lam, normal approximation guard for large lam
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


def _period(rng, path, team, period, minutes):
    frac = minutes / 40.0
    for p in team.players:
        for kind, rate in (("FG2", p.fg2_per40), ("FG3", p.fg3_per40), ("FT", p.ft_per40)):
            for _ in range(_poisson(rng, rate * frac)):
                path.events.append(Event(team.team_id, p.player_id, period, kind))


def simulate_game(home: TeamInput, away: TeamInput, rng: random.Random) -> GamePath:
    home.validate()
    away.validate()
    if home.team_id == away.team_id:
        raise FoundationError(f"{SPORT}_TEAM_IDENTITY_COLLISION", home.team_id)
    both = home.roster & away.roster
    if both:
        raise FoundationError(f"{SPORT}_PLAYER_ON_BOTH_TEAMS", sorted(both)[0])
    if not isinstance(rng, random.Random):
        raise FoundationError(f"{SPORT}_RNG_REQUIRED")
    path = GamePath(home.team_id, away.team_id)
    for q in range(1, REG_PERIODS + 1):
        for t in (home, away):
            _period(rng, path, t, q, REG_PERIOD_MIN)
    period = REG_PERIODS
    while path.points(home.team_id) == path.points(away.team_id):
        period += 1
        if period - REG_PERIODS > MAX_OT:
            raise FoundationError(f"{SPORT}_OT_DID_NOT_RESOLVE")
        for t in (home, away):
            _period(rng, path, t, period, OT_MIN)
    path.periods_played = period
    check_path(path, home, away)
    return path


def check_path(path: GamePath, home: TeamInput, away: TeamInput):
    rosters = {home.team_id: home.roster, away.team_id: away.roster}
    if {path.home_id, path.away_id} != set(rosters):
        raise FoundationError(f"{SPORT}_PATH_TEAM_MISMATCH")
    if not isinstance(path.periods_played, int) or path.periods_played < REG_PERIODS:
        raise FoundationError(f"{SPORT}_PERIODS_INVALID")
    for e in path.events:
        if e.team_id not in rosters:
            raise FoundationError(f"{SPORT}_EVENT_UNKNOWN_TEAM", str(e.team_id))
        if e.player_id not in rosters[e.team_id]:
            raise FoundationError(f"{SPORT}_PLAYER_NOT_ON_TEAM", str(e.player_id))
        if e.kind not in EVENT_POINTS:
            raise FoundationError(f"{SPORT}_EVENT_KIND_INVALID", str(e.kind))
        if not isinstance(e.period, int) or not 1 <= e.period <= path.periods_played:
            raise FoundationError(f"{SPORT}_PERIOD_INVALID", str(e.period))
    for t, roster in rosters.items():
        if path.points(t) != sum(path.player_points(p) for p in roster):
            raise FoundationError(f"{SPORT}_PLAYER_TEAM_POINTS_MISMATCH", t)
    # OT periods only exist if the score was tied entering each of them
    for p in range(REG_PERIODS, path.periods_played):
        upto = tuple(range(1, p + 1))
        if path.points(path.home_id, upto) != path.points(path.away_id, upto):
            raise FoundationError(f"{SPORT}_OT_AFTER_DECIDED_GAME", str(p + 1))
    h, a = path.final_score()
    if h == a:
        raise FoundationError(f"{SPORT}_GAME_ENDED_TIED")
    return True


def _ou(value, line):
    if isinstance(line, bool) or not isinstance(line, (int, float)) or not math.isfinite(line):
        raise FoundationError(f"{SPORT}_LINE_NONFINITE", repr(line))
    return "OVER" if value > line else "UNDER" if value < line else "PUSH"


SEGMENTS = {"1H": (1,)}


def _segment(path, segment):
    if segment == "GAME":
        return None
    if segment == "2H":                          # includes OT
        return tuple(range(2, path.periods_played + 1))
    if segment in SEGMENTS:
        return SEGMENTS[segment]
    raise FoundationError(f"{SPORT}_SEGMENT_INVALID", str(segment))


def settle(path: GamePath, market: str, *, selection=None, line=None,
           segment="GAME", player_id=None, team_id=None):
    if illinois_excluded(path.home_id, path.away_id):
        raise FoundationError("ILLINOIS_COLLEGE_EXCLUDED")
    per = _segment(path, segment)
    h, a = path.points(path.home_id, per), path.points(path.away_id, per)
    sides = (path.home_id, path.away_id)
    if market == "MONEYLINE":
        if selection not in sides:
            raise FoundationError(f"{SPORT}_SELECTION_IDENTITY_MISMATCH", str(selection))
        if h == a:     # only possible for a segment; 2-way segment ML pushes
            return "PUSH"
        return "WIN" if (selection == path.home_id) == (h > a) else "LOSE"
    if market == "SPREAD":
        if selection not in sides:
            raise FoundationError(f"{SPORT}_SELECTION_IDENTITY_MISMATCH", str(selection))
        m = (h - a) if selection == path.home_id else (a - h)
        _ou(0, line)   # validates the line before arithmetic
        return {"OVER": "WIN", "UNDER": "LOSE", "PUSH": "PUSH"}[_ou(m + line, 0)]
    if market == "TOTAL":
        return _ou(h + a, line)
    if market == "TEAM_TOTAL":
        if selection not in sides:
            raise FoundationError(f"{SPORT}_SELECTION_IDENTITY_MISMATCH", str(selection))
        return _ou(h if selection == path.home_id else a, line)
    if market == "GOES_TO_OT":
        if selection not in ("YES", "NO"):
            raise FoundationError(f"{SPORT}_SELECTION_IDENTITY_MISMATCH", str(selection))
        return "WIN" if (selection == "YES") == (path.periods_played > REG_PERIODS) else "LOSE"
    if market in ("PLAYER_POINTS", "PLAYER_THREES"):
        if segment != "GAME":
            raise FoundationError(f"{SPORT}_PLAYER_SEGMENT_NOT_SUPPORTED", segment)
        if team_id not in sides:
            raise FoundationError(f"{SPORT}_TEAM_IDENTITY_MISMATCH", str(team_id))
        if not isinstance(player_id, str) or not player_id:
            raise FoundationError(f"{SPORT}_PLAYER_ID_MISSING")
        if any(e.player_id == player_id and e.team_id != team_id for e in path.events):
            raise FoundationError(f"{SPORT}_PLAYER_IDENTITY_MISMATCH", str(player_id))
        v = path.player_points(player_id) if market == "PLAYER_POINTS" \
            else path.player_count(player_id, "FG3")
        return _ou(v, line)
    raise FoundationError(f"{SPORT}_MARKET_NO_SETTLEMENT", market)


def settle_player_prop(path, home, away, market, player_id, line, team_id):
    rosters = {home.team_id: home.roster, away.team_id: away.roster}
    if team_id not in rosters:
        raise FoundationError(f"{SPORT}_TEAM_IDENTITY_MISMATCH", str(team_id))
    if player_id not in rosters[team_id]:
        raise FoundationError(f"{SPORT}_PLAYER_IDENTITY_MISMATCH", str(player_id))
    return settle(path, market, player_id=player_id, line=line, team_id=team_id)


_SIM = "joint scoring-event skeleton + settlement; caller-supplied rates, no fit, no backtest"
MARKET_TERMINALS = {
    "MONEYLINE": ("RESEARCH_ONLY", _SIM),
    "SPREAD": ("RESEARCH_ONLY", _SIM),
    "TOTAL": ("RESEARCH_ONLY", _SIM),
    "TEAM_TOTAL": ("RESEARCH_ONLY", _SIM),
    "QUARTER_MARKETS": ("NOT_OFFERED", "men's college basketball is played in halves"),
    "HALF_MARKETS": ("RESEARCH_ONLY", _SIM + "; 1H excludes OT, 2H includes OT"),
    "GOES_TO_OT": ("RESEARCH_ONLY", _SIM),
    "PLAYER_POINTS": ("RESEARCH_ONLY", _SIM),
    "PLAYER_THREES": ("RESEARCH_ONLY", _SIM),
    "PLAYER_REBOUNDS": ("NO_ENGINE", "no rebound/miss process"),
    "PLAYER_ASSISTS": ("NO_ENGINE", "no assist linkage process"),
    "PLAYER_PRA": ("NO_ENGINE", "needs rebounds + assists engines"),
    "PLAYER_STEALS_BLOCKS": ("NO_ENGINE", "no defensive event process"),
    "PLAYER_TURNOVERS": ("NO_ENGINE", "no possession/turnover process"),
    "DOUBLE_DOUBLE": ("NO_ENGINE", "needs rebounds + assists engines"),
    "FIRST_BASKET": ("NO_SETTLEMENT", "first-basket ordering/settlement not encoded"),
    "WINNING_MARGIN": ("NO_SETTLEMENT", "band settlement not encoded"),
    "RACE_TO_POINTS": ("NO_ENGINE", "event ordering within a period not modeled"),
    "SERIES_FUTURES": ("NOT_OFFERED", "outside this foundation's scope"),
}
for _m, (_t, _r) in MARKET_TERMINALS.items():
    assert _t in _ALLOWED, (_m, _t)


def market_terminal(market: str, *teams):
    """One terminal per market; an Illinois college on either side overrides it."""
    t, reason = MARKET_TERMINALS.get(market, ("NO_ENGINE", "market not inventoried"))
    if illinois_excluded(*teams):
        t, reason = "BLOCKED_BY_AUTHORIZATION", "ILLINOIS_COLLEGE_EXCLUDED"
    return {"sport": SPORT, "market": market, "terminal": t, "reason": reason,
            "validation": VALIDATION, "probability": None, "price": None, "ev": None}
