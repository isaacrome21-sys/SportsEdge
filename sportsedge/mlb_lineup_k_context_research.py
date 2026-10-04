"""Held-out validation of context lane 2c: announced-lineup strikeout rate -> pitcher K.

Protocol: docs/MLB_LINEUP_K_CONTEXT_PREREG.md (pre-registered). Research only: this
module never changes model_p in production. The baseline candidate reproduces the
production PITCHER_K price exactly (own last <=10 starts rescaled by the lane-1
opponent-K index, beta 1), tested against ``pitcher_joint_engine``.
"""
from __future__ import annotations

import hashlib
from bisect import bisect_left
from math import inf
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from sportsedge.mlb_opp_k_context_research import OppIndex
from sportsedge.mlb_pitcher_prior_research import MIN_PRODUCTION_STARTS, OWN_WINDOW, posterior_over, rps
from sportsedge.mlb_umpire_context_research import UStart, adjusted_mass_over, cluster_bootstrap, typical_metrics

PREREG_PATH = Path(__file__).resolve().parents[1] / "docs" / "MLB_LINEUP_K_CONTEXT_PREREG.md"
THRESH = np.arange(0, 20) + 0.5
OPP_K_BETA = 1.0  # production lane 1 (#1509/#1513), part of the baseline
SLOT_WEIGHTS = (4.65, 4.55, 4.45, 4.35, 4.25, 4.15, 4.05, 3.95, 3.85)
WS = (200.0, 600.0)
GAMMAS = (0.25, 0.5, 0.75, 1.0)
BASELINE = (0.0, 0.0)
CANDIDATES: tuple[tuple[float, float], ...] = (BASELINE,) + tuple((w, g) for w in WS for g in GAMMAS)
ECE_SLACK = 0.005


class LineupResearchError(ValueError):
    pass


def prereg_sha256() -> str:
    return hashlib.sha256(PREREG_PATH.read_bytes()).hexdigest()


def label(cand: tuple[float, float]) -> str:
    return "baseline (production)" if cand == BASELINE else f"W_b={cand[0]:g} gamma={cand[1]:g}"


def _int(v: Any) -> int | None:
    try:
        out = int(v)
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def final_games_from_schedule(payload: Mapping[str, Any]) -> dict[int, str]:
    """gamePk -> officialDate for final regular-season games in a schedule payload."""
    out: dict[int, str] = {}
    for block in payload.get("dates") or []:
        if not isinstance(block, Mapping):
            continue
        for game in block.get("games") or []:
            if not isinstance(game, Mapping):
                continue
            pk = _int(game.get("gamePk"))
            status = game.get("status") or {}
            if pk is None or str(game.get("gameType") or "R") != "R":
                continue
            if str(status.get("abstractGameState") or "") != "Final" or str(status.get("codedGameState") or "F") not in ("F", "O"):
                continue
            d = str(game.get("officialDate") or block.get("date") or "")[:10]
            if len(d) == 10:
                out[pk] = d
    return out


def parse_boxscore(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Compact boxscore: {team_id: batting order (9 ids) or None} and {player_id: (K, PA)}."""
    orders: dict[int, tuple[int, ...] | None] = {}
    lines: dict[int, tuple[int, int]] = {}
    teams = payload.get("teams") or {}
    for side in ("away", "home"):
        box = teams.get(side) or {}
        if not isinstance(box, Mapping):
            continue
        tid = _int((box.get("team") or {}).get("id"))
        if tid is None:
            continue
        order = [_int(x) for x in (box.get("battingOrder") or [])]
        ok = len(order) == 9 and all(order) and len(set(order)) == 9
        orders[tid] = tuple(order) if ok else None  # type: ignore[arg-type]
        players = box.get("players") or {}
        if not isinstance(players, Mapping):
            continue
        for row in players.values():
            if not isinstance(row, Mapping):
                continue
            pid = _int((row.get("person") or {}).get("id"))
            bat = (row.get("stats") or {}).get("batting") or {}
            if pid is None or not isinstance(bat, Mapping) or not bat:
                continue
            try:
                k = int(bat.get("strikeOuts", 0) or 0)
                if bat.get("plateAppearances") is not None:
                    pa = int(bat.get("plateAppearances"))
                else:
                    pa = sum(int(bat.get(f, 0) or 0) for f in ("atBats", "baseOnBalls", "hitByPitch", "sacFlies", "sacBunts", "catchersInterference"))
            except (TypeError, ValueError):
                continue
            if pa > 0 and 0 <= k <= pa:
                lines[pid] = (k, pa)
    return {"orders": orders, "lines": lines}


class LineupIndex:
    """Batter rates r_b and the lineup index L (see prereg), strictly prior to the date."""

    def __init__(self, team_rows: Mapping[tuple[int, int], Sequence[tuple[str, int, int]]],
                 batter_rows: Mapping[int, Sequence[tuple[str, int, int]]]):
        # team_rows[(team, season)] = [(date, K, PA)]; batter_rows[batter] = [(date, K, PA)] all seasons.
        league: dict[int, list[tuple[str, int, int]]] = {}
        for (_team, season), rows in team_rows.items():
            league.setdefault(season, []).extend(rows)
        self._league = {s: self._cum(rows) for s, rows in league.items()}
        self._bat: dict[tuple[int, int], tuple] = {}
        per: dict[tuple[int, int], list[tuple[str, int, int]]] = {}
        for b, rows in batter_rows.items():
            for d, k, pa in rows:
                per.setdefault((b, int(d[:4])), []).append((d, k, pa))
        self._bat = {key: self._cum(rows) for key, rows in per.items()}
        self._memo: dict[tuple, float] = {}

    @staticmethod
    def _cum(rows):
        rows = sorted(rows)
        return ([r[0] for r in rows], np.concatenate([[0], np.cumsum([r[1] for r in rows])]),
                np.concatenate([[0], np.cumsum([r[2] for r in rows])]))

    @staticmethod
    def _before(cum, d: str | None) -> tuple[float, float]:
        if cum is None:
            return 0.0, 0.0
        dates, k, pa = cum
        i = len(dates) if d is None else bisect_left(dates, d)
        return float(k[i]), float(pa[i])

    def _two_season(self, cums: Mapping, key_prev, key_cur, d: str) -> tuple[float, float]:
        kp, pp = self._before(cums.get(key_prev), None)
        kc, pc = self._before(cums.get(key_cur), d)
        return kp + kc, pp + pc

    def league_rate(self, d: str, season: int) -> float:
        k, pa = self._two_season(self._league, season - 1, season, d)
        if pa <= 0 or k <= 0:
            raise LineupResearchError(f"no league PA before {d}")
        return k / pa

    def batter_rate(self, b: int, d: str, season: int, w: float) -> float:
        r_l = self.league_rate(d, season)
        k, pa = self._two_season(self._bat, (b, season - 1), (b, season), d)
        return (k + w * r_l) / (pa + w)

    def lineup_rel(self, order: Sequence[int], d: str, season: int, w: float) -> float:
        key = (tuple(order), d, season, w)
        if key not in self._memo:
            if len(order) != 9:
                raise LineupResearchError("lineup needs exactly 9 batters")
            r_l = self.league_rate(d, season)
            num = sum(ws * self.batter_rate(b, d, season, w) for ws, b in zip(SLOT_WEIGHTS, order))
            self._memo[key] = num / (r_l * sum(SLOT_WEIGHTS))
        return self._memo[key]


def opp_order(lineups: Mapping[int, Mapping[int, Any]], s: UStart) -> tuple[int, ...] | None:
    return (lineups.get(s.game_pk) or {}).get(s.opp_id)


def deviation(s: UStart, lineups, lidx: LineupIndex, opp: OppIndex, w: float) -> float | None:
    """D = L / opp_rel for the opponent lineup of start s, or None if the lineup is unknown."""
    order = opp_order(lineups, s)
    if order is None:
        return None
    return lidx.lineup_rel(order, s.date, s.season, w) / opp.rel(s.opp_id, s.season, s.date)


def predict(own: Sequence[UStart], target: UStart, lineups, lidx: LineupIndex, opp: OppIndex,
            cand: tuple[float, float]) -> np.ndarray:
    """Engine-style P(over) at every K threshold; the baseline is the production price."""
    if not own:
        raise LineupResearchError("needs own history")
    w, gamma = cand
    rt = opp.rel(target.opp_id, target.season, target.date)
    d_t = None
    if gamma != 0:
        d_t = deviation(target, lineups, lidx, opp, w)
        if d_t is None:
            raise LineupResearchError("target lineup unknown")
    xs = []
    for r in own:
        x = float(r.k) * (rt / opp.rel(r.opp_id, r.season, r.date)) ** OPP_K_BETA
        if gamma != 0:
            d_i = deviation(r, lineups, lidx, opp, w)
            x *= (d_t / (1.0 if d_i is None else d_i)) ** gamma
        xs.append(x)
    return posterior_over(adjusted_mass_over(xs, "k"), float(len(own)))


def evaluate(eval_starts: Sequence[UStart], window: Mapping[UStart, list[UStart]], lineups, lidx: LineupIndex,
             opp: OppIndex, candidates: Sequence[tuple[float, float]] = CANDIDATES) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    counts = {"no_target_lineup": 0, "history_starts": 0, "history_unknown_lineup": 0}
    for s in eval_starts:
        prior = window.get(s, [])
        if len(prior) < MIN_PRODUCTION_STARTS:
            continue
        if opp_order(lineups, s) is None:
            counts["no_target_lineup"] += 1
            continue
        own = prior[-OWN_WINDOW:]
        counts["history_starts"] += len(own)
        counts["history_unknown_lineup"] += sum(1 for r in own if opp_order(lineups, r) is None)
        rows.append({
            "pitcher_id": s.pitcher_id, "y": s.k, "date": s.date,
            "dev": deviation(s, lineups, lidx, opp, WS[0]),
            "preds": {c: predict(own, s, lineups, lidx, opp, c) for c in candidates},
        })
    return rows, counts


def rps_table(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[float, float], float]:
    if not rows:
        raise LineupResearchError("no rows")
    return {c: float(np.mean([rps(r["preds"][c], r["y"], THRESH) for r in rows])) for c in rows[0]["preds"]}


def select(table: Mapping[tuple[float, float], float], order: Sequence[tuple[float, float]] = CANDIDATES) -> tuple[float, float]:
    """Lowest RPS; ties go to the earlier candidate (baseline first)."""
    best, val = None, inf
    for c in order:
        if c in table and table[c] < val - 1e-12:
            best, val = c, table[c]
    if best is None:
        raise LineupResearchError("no candidate")
    return best


def ship_decision(test_rows, cand: tuple[float, float]) -> dict[str, Any]:
    rule1 = cand != BASELINE and cand[1] != 0
    boot = cluster_bootstrap(test_rows, cand, BASELINE, "k") if rule1 else None
    base = typical_metrics(test_rows, BASELINE, "k")
    sel = typical_metrics(test_rows, cand, "k")
    rule2 = bool(boot and boot["hi"] < 0)
    rule3 = sel["ece"] <= base["ece"] + ECE_SLACK
    return {"candidate": label(cand), "bootstrap_vs_base": boot, "typical_base": base, "typical_selected": sel,
            "rule1_not_baseline": rule1, "rule2_beats_base": rule2, "rule3_calibrated": bool(rule3),
            "ships": bool(rule1 and rule2 and rule3)}
