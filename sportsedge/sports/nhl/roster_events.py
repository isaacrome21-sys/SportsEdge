"""Roster-level NHL player event allocation on shared game paths.

Each simulated team goal has exactly one scorer and at most two distinct assists.
Role shares are explicit PIT-safe/versioned inputs; no fitted defaults live here.
"""
from dataclasses import dataclass
import hashlib, math, random
from .simulation import NHLGamePaths

@dataclass(frozen=True)
class NHLRosterEventRole:
    player_id: str
    team: str
    captured_at: str
    source: str
    version: str
    goal_weight: float
    primary_assist_weight: float
    secondary_assist_weight: float
    lineup_status: str
    def validate(self):
        if not all((self.player_id,self.captured_at,self.source,self.version)): raise ValueError("identity/provenance required")
        if self.team not in {"HOME","AWAY"}: raise ValueError("team must be HOME or AWAY")
        if self.lineup_status not in {"CONFIRMED","PROJECTED"}: raise ValueError("invalid lineup status")
        if any(not math.isfinite(x) or x<0 for x in (self.goal_weight,self.primary_assist_weight,self.secondary_assist_weight)):
            raise ValueError("event weights must be finite and nonnegative")

@dataclass(frozen=True)
class NHLRosterEventPaths:
    goals: dict[str,tuple[int,...]]
    assists: dict[str,tuple[int,...]]
    points: dict[str,tuple[int,...]]
    seed: int
    version: str

def _pick(rng, roles, attr, excluded=frozenset()):
    pool=[r for r in roles if r.player_id not in excluded and getattr(r,attr)>0]
    total=sum(getattr(r,attr) for r in pool)
    if total<=0: return None
    u=rng.random()*total; acc=0.0
    for r in pool:
        acc+=getattr(r,attr)
        if u<=acc: return r
    return pool[-1]

def simulate_roster_events(game:NHLGamePaths, roles:list[NHLRosterEventRole], *, team:str, version:str, seed:int|None=None):
    if not roles or not version: raise ValueError("roster and version required")
    if any(r.team!=team for r in roles): raise ValueError("mixed-team roster")
    if len({r.player_id for r in roles})!=len(roles): raise ValueError("duplicate player")
    for r in roles: r.validate()
    if sum(r.goal_weight for r in roles)<=0: raise ValueError("positive scorer weight required")
    team_goals=game.home_regulation if team=="HOME" else game.away_regulation
    if seed is None:
        sig="|".join(f"{r.player_id}:{r.version}" for r in sorted(roles,key=lambda x:x.player_id))
        payload=f"{game.seed}|{game.engine_version}|{team}|{version}|{sig}|roster-events-v1"
        seed=int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8],"big")
    rng=random.Random(int(seed)); n=len(team_goals)
    goals={r.player_id:[0]*n for r in roles}; assists={r.player_id:[0]*n for r in roles}
    for i,total in enumerate(team_goals):
        for _ in range(total):
            scorer=_pick(rng,roles,"goal_weight"); goals[scorer.player_id][i]+=1
            primary=_pick(rng,roles,"primary_assist_weight",{scorer.player_id})
            excluded={scorer.player_id}
            if primary: assists[primary.player_id][i]+=1; excluded.add(primary.player_id)
            secondary=_pick(rng,roles,"secondary_assist_weight",excluded)
            if secondary: assists[secondary.player_id][i]+=1
    frozen_g={k:tuple(v) for k,v in goals.items()}; frozen_a={k:tuple(v) for k,v in assists.items()}
    points={k:tuple(g+a for g,a in zip(frozen_g[k],frozen_a[k])) for k in frozen_g}
    return NHLRosterEventPaths(frozen_g,frozen_a,points,int(seed),version)
