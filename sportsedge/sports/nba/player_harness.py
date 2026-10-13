"""NBA player-layer evaluation per docs/NBA_PLAYER_LAYER_PREREG_20261013.md.

Point in time: cutoff = earliest tip on the target's America/Chicago slate date.
Games train only when FINAL and available by the cutoff (start + 4h <= cutoff).
Availability is a RETROSPECTIVE_AVAILABILITY_ORACLE (who played in the target game).
That is look-ahead, so these numbers are conditional on knowing who plays.
Production availability without verified evidence stays UNKNOWN, so props are BLOCKED.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from math import exp
from zoneinfo import ZoneInfo

from .asof_team_ratings import fit_asof
from .player_layer import Availability, PlayerLog, allocate, build_rotation, player_market, player_marginal
from .quarter_joint_sim import calibrate, simulate

CT = ZoneInfo("America/Chicago")
FINAL_BUFFER = timedelta(hours=4)
LINES = {"PTS": (9.5, 14.5, 19.5, 24.5), "REB": (3.5, 5.5, 7.5), "AST": (2.5, 4.5, 6.5)}
FIELD = {"PTS": "points", "REB": "rebounds", "AST": "assists"}
AVAILABILITY_LABEL = "RETROSPECTIVE_AVAILABILITY_ORACLE"
N_PATHS = 400


def trainable(start: datetime, cutoff: datetime) -> bool:
    return start + FINAL_BUFFER <= cutoff


def _poisson_over(mean: float, line: float) -> float:
    k, term, cdf = 0, exp(-mean), 0.0
    while k <= line:
        cdf += term
        k += 1
        term *= mean / k
    return 1.0 - cdf


def run_player_harness(games, quarter_games, logs, *, min_team_games=5, min_player_games=3, n_paths=N_PATHS,
                       version: str = "v1", baseline: str = "naive"):
    if baseline not in {"naive", "naive_oracle"}:
        raise ValueError("BASELINE_INVALID")
    """games: NBAGame list; quarter_games: QuarterGame list; logs: PlayerLog list (minutes > 0 only)."""
    qmap = {q.game_id: q for q in quarter_games}
    games = sorted((g for g in games if g.game_id in qmap), key=lambda g: (g.start, g.game_id))
    logs_by_game = defaultdict(list)
    for l in logs:
        logs_by_game[l.game_id].append(l)
    by_day = defaultdict(list)
    for g in games:
        by_day[g.start.astimezone(CT).date()].append(g)
    acc = {s: {str(x): [0, 0.0, 0.0] for x in LINES[s]} for s in LINES}
    mins = [0, 0.0, 0.0]
    for day in sorted(by_day):
        slate = by_day[day]
        cutoff = min(g.start for g in slate)
        train = [g for g in games if trainable(g.start, cutoff)]
        if len(train) < 30:
            continue
        tids = {g.game_id for g in train}
        tlogs = [l for gid in tids for l in logs_by_game[gid]]
        r = fit_asof(train, cutoff)
        cal = calibrate([qmap[g.game_id] for g in train], cutoff)
        by_player = defaultdict(list)
        for l in sorted(tlogs, key=lambda l: (l.start, l.game_id)):
            by_player[(l.team, l.player_id)].append(l)
        for g in slate:
            if min(r.games_by_team.get(g.home, 0), r.games_by_team.get(g.away, 0)) < min_team_games:
                continue
            target = logs_by_game.get(g.game_id) or []
            if not target:
                continue
            p = r.predict(g.home, g.away)
            H, A = simulate(cal, p["home_points"], p["away_points"], n=n_paths, seed=int(g.game_id) % (2**31))
            for team, paths in ((g.home, H.sum(1)), (g.away, A.sum(1))):
                played = {l.player_id: l for l in target if l.team == team}
                try:
                    pre = build_rotation(tlogs, team, cutoff)
                except ValueError:
                    continue
                avail = {pid: Availability("AVAILABLE" if pid in played else "OUT", AVAILABILITY_LABEL,
                                           cutoff - timedelta(seconds=1)) for pid in pre.players}
                try:
                    rot = build_rotation(tlogs, team, cutoff, availability=avail,
                                         minutes_mode="played" if version == "v2" else "v1_zero_fill")
                except ValueError:
                    continue
                alloc = allocate(rot, paths, seed=int(g.game_id) % (2**31)) if version == "v1" else None
                scale = 1.0
                if baseline == "naive_oracle":  # same after-the-fact who-played knowledge as the candidate
                    raw = [sum(l.minutes for l in h) / len(h) for h in
                           (by_player.get((team, q), [])[-10:] for q in played) if h]
                    scale = 240.0 / sum(raw) if raw and sum(raw) > 0 else 1.0
                for pid, actual in played.items():
                    hist = by_player.get((team, pid), [])[-10:]
                    if pid not in rot.players or len(hist) < min_player_games:
                        continue
                    i = rot.players.index(pid)
                    nm = scale * sum(l.minutes for l in hist) / len(hist)
                    mins[0] += 1
                    mins[1] += abs(rot.exp_minutes[i] - actual.minutes)
                    mins[2] += abs(nm - actual.minutes)
                    for s, lines in LINES.items():
                        nmean = scale * sum(getattr(l, FIELD[s]) for l in hist) / len(hist)
                        y_val = getattr(actual, FIELD[s])
                        for x in lines:
                            m = (player_market(rot, alloc, pid, s, x) if version == "v1"
                                 else player_marginal(rot, hist, pid, s, x))
                            assert m["status"] in {"WATCH", "BLOCKED"} and m["play_authority"] is False
                            y = int(y_val > x)
                            a = acc[s][str(x)]
                            a[0] += 1
                            a[1] += (m["over"] - y) ** 2
                            a[2] += (_poisson_over(nmean, x) - y) ** 2
    out = {s: {x: {"n": v[0], "brier_cand": round(v[1] / max(v[0], 1), 5), "brier_naive": round(v[2] / max(v[0], 1), 5)}
               for x, v in d.items()} for s, d in acc.items()}
    m = {"n": mins[0], "mae_cand": round(mins[1] / max(mins[0], 1), 3), "mae_naive": round(mins[2] / max(mins[0], 1), 3)}
    decision = {s: "PASS_RESEARCH" if all(v["brier_cand"] < v["brier_naive"] for v in d.values()) and
                any(v["n"] for v in d.values()) else "FAIL" for s, d in out.items()}
    decision["MINUTES"] = "PASS_RESEARCH" if m["n"] and m["mae_cand"] < m["mae_naive"] else "FAIL"
    return {"version": version, "baseline": baseline, "stats": out, "minutes": m, "decision": decision, "availability": AVAILABILITY_LABEL,
            "market_baseline": "MISSING", "prop_status_ceiling": "WATCH"}


def parse_player_box(d: dict, team_by_id: dict) -> list:
    if not d.get("completed"):
        return []
    start = datetime.fromisoformat(d["date"].replace("Z", "+00:00"))
    out = []
    for t in d.get("teams") or []:
        team = team_by_id.get(str(t["team_id"]))
        if team is None:
            continue
        for p in t["players"]:
            try:
                mn = float(p["MIN"])
                pts, reb, ast = int(p["PTS"]), int(p["REB"]), int(p["AST"])
            except (TypeError, ValueError, KeyError):
                continue
            if p.get("dnp") or mn <= 0:
                continue
            out.append(PlayerLog(str(p["id"]), team, str(d["id"]), start, mn, pts, reb, ast))
    return out
