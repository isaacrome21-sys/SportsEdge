"""Held-out validation of context lane 2b: home-plate umpire -> pitcher K and BB.

Protocol: docs/MLB_UMPIRE_CONTEXT_PREREG.md (pre-registered). Research only: this
module never changes model_p in production. ``beta = 0`` reproduces the production
price of each market exactly (K: lane-1 opponent-K adjusted, beta 1; BB: own history),
tested against ``pitcher_joint_engine``.
"""
from __future__ import annotations

import hashlib
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date as _date, timedelta
from math import floor, inf
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from sportsedge.mlb_opp_k_context_research import BOOT_SEED, ECE_SLACK, OppIndex
from sportsedge.mlb_pitcher_prior_research import MIN_PRODUCTION_STARTS, OWN_WINDOW, posterior_over, rps

PREREG_PATH = Path(__file__).resolve().parents[1] / "docs" / "MLB_UMPIRE_CONTEXT_PREREG.md"
STATS = ("k", "bb")
CAPS = {"k": 20, "bb": 10}
THRESH = {"k": np.arange(0, 20) + 0.5, "bb": np.arange(0, 10) + 0.5}
TYPICAL = {"k": (3.5, 4.5, 5.5, 6.5), "bb": (0.5, 1.5, 2.5, 3.5)}
OPP_K_BETA = 1.0  # production lane 1 (#1509/#1513), part of the 2b-K baseline
WINDOW_DAYS = 365
WS = (2000.0, 6000.0)
BETAS = (0.5, 1.0, 1.5, 2.0)
BASELINE = (0.0, 0.0)
CANDIDATES: tuple[tuple[float, float], ...] = (BASELINE,) + tuple((w, b) for w in WS for b in BETAS)


class UmpireResearchError(ValueError):
    pass


@dataclass(frozen=True)
class UStart:
    pitcher_id: int
    season: int
    date: str
    game_pk: int
    team_id: int
    opp_id: int
    k: int
    bb: int


def prereg_sha256() -> str:
    return hashlib.sha256(PREREG_PATH.read_bytes()).hexdigest()


def label(cand: tuple[float, float]) -> str:
    return "baseline (production)" if cand == BASELINE else f"W={cand[0]:g} beta={cand[1]:g}"


def ustarts_from_gamelog(payload: Mapping[str, Any], *, pitcher_id: int, season: int) -> list[UStart]:
    """Regular-season starts with K, BB, opponent id and gamePk from a StatsAPI pitching gameLog."""
    out: list[UStart] = []
    for block in payload.get("stats") or []:
        if not isinstance(block, Mapping):
            continue
        for split in block.get("splits") or []:
            if not isinstance(split, Mapping):
                continue
            stat = split.get("stat") or {}
            try:
                if float(stat.get("gamesStarted", 0) or 0) < 1:
                    continue
                ks = int(stat.get("strikeOuts", 0) or 0)
                bb = int(stat.get("baseOnBalls", 0) or 0)
                team_id = int((split.get("team") or {}).get("id"))
                opp_id = int((split.get("opponent") or {}).get("id"))
                game_pk = int((split.get("game") or {}).get("gamePk"))
            except (TypeError, ValueError):
                continue
            raw_date = str(split.get("date") or "")[:10]
            if len(raw_date) != 10 or ks < 0 or bb < 0 or game_pk <= 0:
                continue
            out.append(UStart(int(pitcher_id), int(season), raw_date, game_pk, team_id, opp_id, ks, bb))
    return out


def team_game_rows(payload: Mapping[str, Any]) -> list[tuple[int, str, int, int, int]]:
    """(gamePk, date, K, BB, PA) per game from a team hitting gameLog."""
    out: list[tuple[int, str, int, int, int]] = []
    for block in payload.get("stats") or []:
        if not isinstance(block, Mapping):
            continue
        for split in block.get("splits") or []:
            if not isinstance(split, Mapping):
                continue
            stat = split.get("stat") or {}
            try:
                pa = int(stat.get("plateAppearances"))
                ks = int(stat.get("strikeOuts"))
                bb = int(stat.get("baseOnBalls"))
                game_pk = int((split.get("game") or {}).get("gamePk"))
            except (TypeError, ValueError):
                continue
            raw_date = str(split.get("date") or "")[:10]
            if len(raw_date) != 10 or pa <= 0 or game_pk <= 0 or not (0 <= ks <= pa and 0 <= bb <= pa):
                continue
            out.append((game_pk, raw_date, ks, bb, pa))
    return out


def home_plate_by_game(schedule_payload: Mapping[str, Any]) -> dict[int, int]:
    """gamePk -> home-plate umpire id from a schedule payload hydrated with officials."""
    from sportsedge.mlb_umpire_source import _official_from_rows

    out: dict[int, int] = {}
    for block in schedule_payload.get("dates") or []:
        if not isinstance(block, Mapping):
            continue
        for game in block.get("games") or []:
            if not isinstance(game, Mapping):
                continue
            try:
                pk = int(game.get("gamePk"))
            except (TypeError, ValueError):
                continue
            hp = _official_from_rows(game.get("officials"))
            if hp:
                out[pk] = int(hp["umpire_id"])
    return out


def game_totals(team_rows: Sequence[tuple[int, str, int, int, int]]) -> dict[int, tuple[str, int, int, int]]:
    """gamePk -> (date, K, BB, PA) summed over both teams; games without exactly two rows are dropped."""
    acc: dict[int, list[tuple[str, int, int, int]]] = {}
    for pk, d, k, bb, pa in team_rows:
        acc.setdefault(pk, []).append((d, k, bb, pa))
    out = {}
    for pk, rows in acc.items():
        if len(rows) != 2 or rows[0][0] != rows[1][0]:
            continue
        out[pk] = (rows[0][0], rows[0][1] + rows[1][1], rows[0][2] + rows[1][2], rows[0][3] + rows[1][3])
    return out


def _minus_days(d: str, days: int) -> str:
    return (_date.fromisoformat(d) - timedelta(days=days)).isoformat()


class UmpIndex:
    """rel_s(u, d; W) per the pre-registration: trailing-365-day shrunk umpire index."""

    def __init__(self, games: Mapping[int, tuple[str, int, int, int]], umpires: Mapping[int, int]):
        per_ump: dict[int, list[tuple[str, int, int, int]]] = {}
        league: list[tuple[str, int, int, int]] = []
        for pk, (d, k, bb, pa) in games.items():
            u = umpires.get(pk)
            if u is None:
                continue
            per_ump.setdefault(u, []).append((d, k, bb, pa))
            league.append((d, k, bb, pa))
        self.usable_games = len(league)
        self._ump = {u: self._cum(rows) for u, rows in per_ump.items()}
        self._league = self._cum(league)
        self._memo: dict[tuple, float] = {}

    @staticmethod
    def _cum(rows):
        rows = sorted(rows)
        z = lambda i: np.concatenate([[0], np.cumsum([r[i] for r in rows])]) if rows else np.zeros(1)  # noqa: E731
        return [r[0] for r in rows], {"k": z(1), "bb": z(2)}, z(3)

    @staticmethod
    def _window(cum, d: str, stat: str) -> tuple[float, float]:
        dates, s, pa = cum
        lo = bisect_left(dates, _minus_days(d, WINDOW_DAYS))
        hi = bisect_left(dates, d)
        return float(s[stat][hi] - s[stat][lo]), float(pa[hi] - pa[lo])

    def rel(self, ump: int | None, d: str, stat: str, w: float) -> float:
        key = (ump, d, stat, w)
        if key not in self._memo:
            self._memo[key] = self._rel(ump, d, stat, w)
        return self._memo[key]

    def _rel(self, ump: int | None, d: str, stat: str, w: float) -> float:
        if ump is None or ump not in self._ump:
            return 1.0
        ls, lpa = self._window(self._league, d, stat)
        if lpa <= 0 or ls <= 0:
            return 1.0
        s, pa = self._window(self._ump[ump], d, stat)
        if pa <= 0:
            return 1.0
        r = ls / lpa
        return (s + w * r) / ((pa + w) * r)


def adjusted_mass_over(values: Sequence[float], stat: str) -> np.ndarray:
    """Fraction of mass above each threshold after linear floor/ceil split (clip [0, cap])."""
    if not values:
        raise UmpireResearchError("empty history")
    cap = CAPS[stat]
    hist = np.zeros(cap + 1)
    for x in values:
        x = min(max(float(x), 0.0), float(cap))
        lo = int(floor(x))
        frac = x - lo
        if lo >= cap:
            hist[cap] += 1.0
            continue
        hist[lo] += 1.0 - frac
        hist[lo + 1] += frac
    support = np.arange(cap + 1)
    return np.array([hist[support > t].sum() for t in THRESH[stat]]) / len(values)


def predict(stat: str, own: Sequence[UStart], target: UStart, umps: Mapping[int, int], uidx: UmpIndex,
            opp: OppIndex | None, cand: tuple[float, float]) -> np.ndarray:
    """Engine-style P(over) at every threshold; the baseline is the production price."""
    if not own:
        raise UmpireResearchError("needs own history")
    w, beta = cand
    xs = []
    for r in own:
        x = float(r.k if stat == "k" else r.bb)
        if stat == "k":
            if opp is None:
                raise UmpireResearchError("2b-K baseline needs the lane-1 opponent index")
            x *= (opp.rel(target.opp_id, target.season, target.date) / opp.rel(r.opp_id, r.season, r.date)) ** OPP_K_BETA
        if beta != 0:
            x *= (uidx.rel(umps.get(target.game_pk), target.date, stat, w) / uidx.rel(umps.get(r.game_pk), r.date, stat, w)) ** beta
        xs.append(x)
    return posterior_over(adjusted_mass_over(xs, stat), float(len(own)))


def evaluate(stat: str, eval_starts: Sequence[UStart], window: Mapping[UStart, list[UStart]], umps: Mapping[int, int],
             uidx: UmpIndex, opp: OppIndex | None, candidates: Sequence[tuple[float, float]] = CANDIDATES) -> tuple[list[dict[str, Any]], int]:
    rows, no_ump = [], 0
    for s in eval_starts:
        prior = window.get(s, [])
        if len(prior) < MIN_PRODUCTION_STARTS:
            continue
        if umps.get(s.game_pk) is None:
            no_ump += 1
            continue
        own = prior[-OWN_WINDOW:]
        rows.append({
            "pitcher_id": s.pitcher_id, "y": s.k if stat == "k" else s.bb, "ump": umps[s.game_pk], "date": s.date,
            "rel": uidx.rel(umps[s.game_pk], s.date, stat, WS[0]),
            "preds": {c: predict(stat, own, s, umps, uidx, opp, c) for c in candidates},
        })
    return rows, no_ump


def rps_table(rows: Sequence[Mapping[str, Any]], stat: str) -> dict[tuple[float, float], float]:
    if not rows:
        raise UmpireResearchError("no rows")
    return {c: float(np.mean([rps(r["preds"][c], r["y"], THRESH[stat]) for r in rows])) for c in rows[0]["preds"]}


def select(table: Mapping[tuple[float, float], float], order: Sequence[tuple[float, float]] = CANDIDATES) -> tuple[float, float]:
    """Lowest RPS; ties go to the earlier candidate (baseline first)."""
    best, val = None, inf
    for c in order:
        if c in table and table[c] < val - 1e-12:
            best, val = c, table[c]
    if best is None:
        raise UmpireResearchError("no candidate")
    return best


def cluster_bootstrap(rows, a, b, stat: str, *, reps: int = 2000, seed: int = BOOT_SEED) -> dict[str, float]:
    clusters: dict[int, list[float]] = {}
    for r in rows:
        d = rps(r["preds"][a], r["y"], THRESH[stat]) - rps(r["preds"][b], r["y"], THRESH[stat])
        clusters.setdefault(r["pitcher_id"], []).append(d)
    if not clusters:
        raise UmpireResearchError("no paired rows")
    sums = np.array([sum(v) for v in clusters.values()])
    counts = np.array([len(v) for v in clusters.values()], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(sums), size=(reps, len(sums)))
    boots = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    return {"diff": float(sums.sum() / counts.sum()), "lo": float(np.quantile(boots, 0.025)),
            "hi": float(np.quantile(boots, 0.975)), "pitchers": float(len(sums)), "starts": float(counts.sum())}


def typical_metrics(rows, cand, stat: str) -> dict[str, float]:
    ps, ys = [], []
    for r in rows:
        for line in TYPICAL[stat]:
            i = int(np.where(np.isclose(THRESH[stat], line))[0][0])
            ps.append(float(r["preds"][cand][i]))
            ys.append(1.0 if r["y"] > line else 0.0)
    if not ps:
        return {"n": 0.0, "logloss": float("nan"), "ece": float("nan")}
    p = np.clip(np.array(ps), 1e-6, 1 - 1e-6)
    y = np.array(ys)
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    bins = np.minimum((p * 10).astype(int), 9)
    ece = sum(float((bins == b).mean() * abs(p[bins == b].mean() - y[bins == b].mean())) for b in range(10) if (bins == b).any())
    return {"n": float(len(p)), "logloss": ll, "ece": float(ece)}


def ship_decision(test_rows, cand: tuple[float, float], stat: str) -> dict[str, Any]:
    rule1 = cand != BASELINE and cand[1] != 0
    boot = cluster_bootstrap(test_rows, cand, BASELINE, stat) if rule1 else None
    base = typical_metrics(test_rows, BASELINE, stat)
    sel = typical_metrics(test_rows, cand, stat)
    rule2 = bool(boot and boot["hi"] < 0)
    rule3 = sel["ece"] <= base["ece"] + ECE_SLACK
    return {"candidate": label(cand), "bootstrap_vs_base": boot, "typical_base": base, "typical_selected": sel,
            "rule1_not_baseline": rule1, "rule2_beats_base": rule2, "rule3_calibrated": bool(rule3),
            "ships": bool(rule1 and rule2 and rule3)}
