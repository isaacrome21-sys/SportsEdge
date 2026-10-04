"""Held-out validation of context lane 1: opponent strikeout rate -> pitcher K.

Protocol: docs/MLB_OPP_K_CONTEXT_PREREG.md (pre-registered). Research only: this
module never changes model_p in production. ``beta = 0`` reproduces the production
own-history K price exactly (tested against ``pitcher_joint_engine``).
"""
from __future__ import annotations

import hashlib
from bisect import bisect_left
from dataclasses import dataclass
from math import floor, inf
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from sportsedge.mlb_pitcher_prior_research import (
    K_CAP,
    K_THRESH,
    MIN_PRODUCTION_STARTS,
    OWN_WINDOW,
    posterior_over,
    rps,
)

PREREG_PATH = Path(__file__).resolve().parents[1] / "docs" / "MLB_OPP_K_CONTEXT_PREREG.md"
BETAS = (0.0, 0.25, 0.5, 0.75, 1.0, 1.25)
PRIOR_PA = 1000.0
TYPICAL_K = (3.5, 4.5, 5.5, 6.5)
BOOT_SEED = 20261004
ECE_SLACK = 0.005


class OppKResearchError(ValueError):
    pass


@dataclass(frozen=True)
class KStart:
    pitcher_id: int
    season: int
    date: str
    game_pk: int
    team_id: int
    opp_id: int
    k: int


def prereg_sha256() -> str:
    return hashlib.sha256(PREREG_PATH.read_bytes()).hexdigest()


def kstarts_from_gamelog(payload: Mapping[str, Any], *, pitcher_id: int, season: int) -> list[KStart]:
    """Regular-season starts with opponent id from a StatsAPI pitching gameLog."""
    out: list[KStart] = []
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
                team_id = int((split.get("team") or {}).get("id"))
                opp_id = int((split.get("opponent") or {}).get("id"))
            except (TypeError, ValueError):
                continue
            raw_date = str(split.get("date") or "")[:10]
            if len(raw_date) != 10 or ks < 0:
                continue
            game_pk = int((split.get("game") or {}).get("gamePk") or 0)
            out.append(KStart(int(pitcher_id), int(season), raw_date, game_pk, team_id, opp_id, ks))
    return out


def team_games_from_gamelog(payload: Mapping[str, Any]) -> list[tuple[str, int, int]]:
    """(date, strikeouts, plate appearances) per game from a team hitting gameLog."""
    out: list[tuple[str, int, int]] = []
    for block in payload.get("stats") or []:
        if not isinstance(block, Mapping):
            continue
        for split in block.get("splits") or []:
            if not isinstance(split, Mapping):
                continue
            stat = split.get("stat") or {}
            try:
                ks = int(stat.get("strikeOuts"))
                pa = int(stat.get("plateAppearances"))
            except (TypeError, ValueError):
                continue
            raw_date = str(split.get("date") or "")[:10]
            if len(raw_date) == 10 and pa > 0 and 0 <= ks <= pa:
                out.append((raw_date, ks, pa))
    out.sort()
    return out


class OppIndex:
    """rel(T, d): shrunk opponent strikeout index, strictly prior to d (see prereg)."""

    def __init__(self, team_games: Mapping[tuple[int, int], Sequence[tuple[str, int, int]]]):
        # team_games[(team_id, season)] = sorted [(date, K, PA)]
        self._cum: dict[tuple[int, int], tuple[list[str], np.ndarray, np.ndarray]] = {}
        self._memo: dict[tuple[int, int, str], float] = {}
        league_rows: dict[int, list[tuple[str, int, int]]] = {}
        for (team, season), rows in team_games.items():
            rows = sorted(rows)
            dates = [r[0] for r in rows]
            self._cum[(team, season)] = (dates, np.concatenate([[0], np.cumsum([r[1] for r in rows])]),
                                         np.concatenate([[0], np.cumsum([r[2] for r in rows])]))
            league_rows.setdefault(season, []).extend(rows)
        self._league: dict[int, tuple[list[str], np.ndarray, np.ndarray]] = {}
        for season, rows in league_rows.items():
            rows.sort()
            self._league[season] = ([r[0] for r in rows], np.concatenate([[0], np.cumsum([r[1] for r in rows])]),
                                    np.concatenate([[0], np.cumsum([r[2] for r in rows])]))

    @staticmethod
    def _before(cum: tuple[list[str], np.ndarray, np.ndarray], date: str | None) -> tuple[float, float]:
        dates, k, pa = cum
        i = len(dates) if date is None else bisect_left(dates, date)
        return float(k[i]), float(pa[i])

    def z_prev(self, team: int, season: int) -> float:
        prev = season - 1
        if (team, prev) not in self._cum or prev not in self._league:
            return 1.0
        tk, tpa = self._before(self._cum[(team, prev)], None)
        lk, lpa = self._before(self._league[prev], None)
        if tpa <= 0 or lpa <= 0 or lk <= 0:
            return 1.0
        return (tk / tpa) / (lk / lpa)

    def rel(self, team: int, season: int, date: str) -> float:
        key = (team, season, date)
        if key not in self._memo:
            self._memo[key] = self._rel(team, season, date)
        return self._memo[key]

    def _rel(self, team: int, season: int, date: str) -> float:
        zp = self.z_prev(team, season)
        if (team, season) not in self._cum or season not in self._league:
            return zp
        tk, tpa = self._before(self._cum[(team, season)], date)
        lk, lpa = self._before(self._league[season], date)
        if tpa <= 0 or lpa <= 0 or lk <= 0:
            return zp
        zc = (tk / tpa) / (lk / lpa)
        return (tpa * zc + PRIOR_PA * zp) / (tpa + PRIOR_PA)


def adjusted_mass_over(values: Sequence[float]) -> np.ndarray:
    """Fraction of mass above each K threshold after linear floor/ceil split (clip at K_CAP)."""
    if not values:
        raise OppKResearchError("empty history")
    hist = np.zeros(K_CAP + 1)
    for x in values:
        x = min(max(float(x), 0.0), float(K_CAP))
        lo = int(floor(x))
        frac = x - lo
        if lo >= K_CAP:
            hist[K_CAP] += 1.0
            continue
        hist[lo] += 1.0 - frac
        hist[lo + 1] += frac
    support = np.arange(K_CAP + 1)
    return np.array([hist[support > t].sum() for t in K_THRESH]) / len(values)


def predict_k(own: Sequence[KStart], target: KStart, index: OppIndex, beta: float) -> np.ndarray:
    """Engine-style P(over) at every K threshold; beta = 0 is the production price."""
    if not own:
        raise OppKResearchError("needs own history")
    if beta == 0:
        xs = [float(r.k) for r in own]
    else:
        rt = index.rel(target.opp_id, target.season, target.date)
        xs = [r.k * (rt / index.rel(r.opp_id, r.season, r.date)) ** beta for r in own]
    return posterior_over(adjusted_mass_over(xs), float(len(own)))


def production_window(starts: Iterable[KStart]) -> dict[KStart, list[KStart]]:
    by_pitcher: dict[int, list[KStart]] = {}
    for s in starts:
        by_pitcher.setdefault(s.pitcher_id, []).append(s)
    out: dict[KStart, list[KStart]] = {}
    for rows in by_pitcher.values():
        rows.sort(key=lambda r: (r.date, r.game_pk))
        for s in rows:
            out[s] = [r for r in rows if r.date < s.date and r.season in (s.season - 1, s.season)]
    return out


def evaluate(eval_starts: Sequence[KStart], window: Mapping[KStart, list[KStart]], index: OppIndex,
             betas: Sequence[float] = BETAS) -> list[dict[str, Any]]:
    rows = []
    for s in eval_starts:
        prior = window.get(s, [])
        if len(prior) < MIN_PRODUCTION_STARTS:
            continue
        own = prior[-OWN_WINDOW:]
        rows.append({
            "pitcher_id": s.pitcher_id, "y_k": s.k, "opp_rel": index.rel(s.opp_id, s.season, s.date),
            "preds": {b: predict_k(own, s, index, b) for b in betas},
        })
    return rows


def rps_table(rows: Sequence[Mapping[str, Any]]) -> dict[float, float]:
    if not rows:
        raise OppKResearchError("no rows")
    return {b: float(np.mean([rps(r["preds"][b], r["y_k"], K_THRESH) for r in rows])) for b in rows[0]["preds"]}


def select_beta(table: Mapping[float, float]) -> float:
    best, val = None, inf
    for b in sorted(table):
        if table[b] < val - 1e-12:
            best, val = b, table[b]
    if best is None:
        raise OppKResearchError("no candidate")
    return best


def cluster_bootstrap(rows: Sequence[Mapping[str, Any]], a: float, b: float, *, reps: int = 2000, seed: int = BOOT_SEED) -> dict[str, float]:
    clusters: dict[int, list[float]] = {}
    for r in rows:
        d = rps(r["preds"][a], r["y_k"], K_THRESH) - rps(r["preds"][b], r["y_k"], K_THRESH)
        clusters.setdefault(r["pitcher_id"], []).append(d)
    if not clusters:
        raise OppKResearchError("no paired rows")
    sums = np.array([sum(v) for v in clusters.values()])
    counts = np.array([len(v) for v in clusters.values()], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(sums), size=(reps, len(sums)))
    boots = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    return {"diff": float(sums.sum() / counts.sum()), "lo": float(np.quantile(boots, 0.025)),
            "hi": float(np.quantile(boots, 0.975)), "pitchers": float(len(sums)), "starts": float(counts.sum())}


def typical_metrics(rows: Sequence[Mapping[str, Any]], beta: float) -> dict[str, float]:
    ps, ys = [], []
    for r in rows:
        for line in TYPICAL_K:
            i = int(np.where(np.isclose(K_THRESH, line))[0][0])
            ps.append(float(r["preds"][beta][i]))
            ys.append(1.0 if r["y_k"] > line else 0.0)
    if not ps:
        return {"n": 0.0, "logloss": float("nan"), "ece": float("nan")}
    p = np.clip(np.array(ps), 1e-6, 1 - 1e-6)
    y = np.array(ys)
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    bins = np.minimum((p * 10).astype(int), 9)
    ece = sum(float((bins == b).mean() * abs(p[bins == b].mean() - y[bins == b].mean())) for b in range(10) if (bins == b).any())
    return {"n": float(len(p)), "logloss": ll, "ece": float(ece)}


def ship_decision(test_rows: Sequence[Mapping[str, Any]], beta: float) -> dict[str, Any]:
    rule1 = beta > 0
    boot = cluster_bootstrap(test_rows, beta, 0.0) if rule1 else None
    base = typical_metrics(test_rows, 0.0)
    sel = typical_metrics(test_rows, beta)
    rule2 = bool(boot and boot["hi"] < 0)
    rule3 = sel["ece"] <= base["ece"] + ECE_SLACK
    return {"beta": beta, "bootstrap_vs_base": boot, "typical_base": base, "typical_selected": sel,
            "rule1_beta_positive": rule1, "rule2_beats_base": rule2, "rule3_calibrated": bool(rule3),
            "ships": bool(rule1 and rule2 and rule3)}
