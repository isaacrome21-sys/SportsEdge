"""As-of NBA minutes/rotation/availability player layer on the joint paths.

Research only. Player points/rebounds/assists are allocated FROM each
simulated team path (``quarter_joint_sim``), so on every path the players'
points sum exactly to the team's points, and rebounds/assists sum to the
path's team rebound/assist totals. Inputs are strictly prior game logs
(``start < as_of``). Availability is UNKNOWN unless backed by evidence
(source + capture time) captured before as_of. Status is never PLAY:
  target UNKNOWN/OUT/DOUBTFUL -> BLOCKED, otherwise WATCH (unvalidated).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Sequence

import numpy as np

VERSION = "NBA_PLAYER_LAYER_V1_20261013"
STATUSES = {"AVAILABLE", "QUESTIONABLE", "DOUBTFUL", "OUT", "UNKNOWN"}


@dataclass(frozen=True)
class PlayerLog:
    player_id: str
    team: str
    game_id: str
    start: datetime
    minutes: float
    points: int
    rebounds: int
    assists: int


@dataclass(frozen=True)
class Availability:
    status: str
    source: str | None = None
    captured_at: datetime | None = None


def availability_for(raw: Mapping[str, Availability] | None, pid: str, as_of: datetime) -> str:
    a = (raw or {}).get(pid)
    if a is None or a.status not in STATUSES or not a.source or a.captured_at is None:
        return "UNKNOWN"
    if a.captured_at.tzinfo is None or a.captured_at >= as_of:
        return "UNKNOWN"  # evidence at/after as-of cannot be used
    return a.status


@dataclass
class TeamRotation:
    team: str
    players: list
    exp_minutes: np.ndarray
    ppm: np.ndarray
    rpm: np.ndarray
    apm: np.ndarray
    reb_per_pt: float
    ast_per_pt: float
    availability: dict = field(default_factory=dict)


def build_rotation(logs: Sequence[PlayerLog], team: str, as_of: datetime, *,
                   availability: Mapping[str, Availability] | None = None,
                   last_n: int = 10, shrink: float = 3.0) -> TeamRotation:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("AS_OF_TIMEZONE_REQUIRED")
    prior = sorted((l for l in logs if l.team == team and l.start < as_of),
                   key=lambda l: (l.start, l.game_id, l.player_id))
    games = sorted({(l.start, l.game_id) for l in prior})
    if len(games) < 5:
        raise ValueError("FEWER_THAN_5_PRIOR_TEAM_GAMES")
    recent = {g for _, g in games[-last_n:]}
    pids = sorted({l.player_id for l in prior if l.game_id in recent})
    status = {p: availability_for(availability, p, as_of) for p in pids}
    tot_m = sum(l.minutes for l in prior)
    lg_ppm = sum(l.points for l in prior) / tot_m
    lg_rpm = sum(l.rebounds for l in prior) / tot_m
    lg_apm = sum(l.assists for l in prior) / tot_m
    mins, ppm, rpm, apm = [], [], [], []
    for p in pids:
        mine = [l for l in prior if l.player_id == p]
        rec = [l for l in mine if l.game_id in recent]
        m = sum(l.minutes for l in rec) / len(recent)  # absent recent games count as 0
        pm = sum(l.minutes for l in mine)
        ppm.append((sum(l.points for l in mine) + shrink * lg_ppm) / (pm + shrink))
        rpm.append((sum(l.rebounds for l in mine) + shrink * lg_rpm) / (pm + shrink))
        apm.append((sum(l.assists for l in mine) + shrink * lg_apm) / (pm + shrink))
        mins.append(0.0 if status[p] == "OUT" else m)
    mins = np.array(mins, float)
    if mins.sum() <= 0:
        raise ValueError("NO_ROTATION_MINUTES")
    pts = sum(l.points for l in prior)
    return TeamRotation(team, pids, mins * (240.0 / mins.sum()), np.array(ppm), np.array(rpm),
                        np.array(apm), sum(l.rebounds for l in prior) / pts,
                        sum(l.assists for l in prior) / pts, status)


def allocate(rot: TeamRotation, team_points, *, seed: int = 0) -> dict:
    """Per-path player PTS/REB/AST that sum exactly to the path's team totals."""
    rng = np.random.default_rng(seed)
    team_points = np.asarray(team_points, int)
    team_reb = rng.poisson(rot.reb_per_pt * team_points)
    team_ast = np.minimum(rng.poisson(rot.ast_per_pt * team_points), team_points // 2)
    out = {}
    for key, rate, totals in (("points", rot.ppm, team_points), ("rebounds", rot.rpm, team_reb),
                              ("assists", rot.apm, team_ast)):
        w = rot.exp_minutes * rate
        w = w / w.sum()
        out[key] = np.stack([rng.multinomial(int(t), w) for t in totals])
    out["team_rebounds"], out["team_assists"] = team_reb, team_ast
    return out


def player_market(rot: TeamRotation, alloc: dict, player_id: str, stat: str, line: float) -> dict:
    if player_id not in rot.players:
        return {"status": "BLOCKED", "reason": "PLAYER_NOT_IN_PRIOR_ROTATION", "play_authority": False}
    i = rot.players.index(player_id)
    if stat == "PRA":
        v = alloc["points"][:, i] + alloc["rebounds"][:, i] + alloc["assists"][:, i]
    else:
        v = alloc[{"PTS": "points", "REB": "rebounds", "AST": "assists"}[stat]][:, i]
    avail = rot.availability.get(player_id, "UNKNOWN")
    blocked = avail in {"UNKNOWN", "OUT", "DOUBTFUL"}
    return {"status": "BLOCKED" if blocked else "WATCH",
            "reason": ("AVAILABILITY_" + avail) if blocked else "UNVALIDATED_RESEARCH",
            "availability": avail, "over": float((v > line).mean()),
            "push": float((v == line).mean()), "play_authority": False, "version": VERSION}
