"""Held-out validation of context lane 2a: opponent profile -> pitcher outs.

Protocol: docs/MLB_OPP_OUTS_CONTEXT_PREREG.md (pre-registered). Research only: this
module never changes model_p in production. ``beta = 0`` reproduces the production
own-history outs price exactly (tested against ``pitcher_joint_engine``).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from math import floor, inf
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from sportsedge.mlb_opp_k_context_research import BOOT_SEED, ECE_SLACK, OppIndex
from sportsedge.mlb_pitcher_prior_research import (
    MIN_PRODUCTION_STARTS,
    OUTS_MAX,
    OUTS_THRESH,
    OWN_WINDOW,
    PriorResearchError,
    outs_from_ip,
    posterior_over,
    rps,
)

PREREG_PATH = Path(__file__).resolve().parents[1] / "docs" / "MLB_OPP_OUTS_CONTEXT_PREREG.md"
INDICES = ("kidx", "obidx")
BETAS = (-1.0, -0.75, -0.5, -0.25, 0.25, 0.5, 0.75, 1.0)
BASELINE = ("base", 0.0)
CANDIDATES: tuple[tuple[str, float], ...] = (BASELINE,) + tuple((i, b) for i in INDICES for b in BETAS)
TYPICAL_OUTS = (14.5, 15.5, 16.5, 17.5)


class OppOutsResearchError(ValueError):
    pass


@dataclass(frozen=True)
class OStart:
    pitcher_id: int
    season: int
    date: str
    game_pk: int
    team_id: int
    opp_id: int
    outs: int


def prereg_sha256() -> str:
    return hashlib.sha256(PREREG_PATH.read_bytes()).hexdigest()


def label(cand: tuple[str, float]) -> str:
    return "baseline (production)" if cand == BASELINE else f"{cand[0]} beta={cand[1]:+g}"


def ostarts_from_gamelog(payload: Mapping[str, Any], *, pitcher_id: int, season: int) -> list[OStart]:
    """Regular-season starts with outs and opponent id from a StatsAPI pitching gameLog."""
    out: list[OStart] = []
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
                outs = outs_from_ip(stat.get("inningsPitched"))
                team_id = int((split.get("team") or {}).get("id"))
                opp_id = int((split.get("opponent") or {}).get("id"))
            except (TypeError, ValueError, PriorResearchError):
                continue
            raw_date = str(split.get("date") or "")[:10]
            if len(raw_date) != 10 or not 0 <= outs <= OUTS_MAX:
                continue
            game_pk = int((split.get("game") or {}).get("gamePk") or 0)
            out.append(OStart(int(pitcher_id), int(season), raw_date, game_pk, team_id, opp_id, outs))
    return out


def team_rows_from_gamelog(payload: Mapping[str, Any]) -> dict[str, list[tuple[str, int, int]]]:
    """Per-game (date, events, PA) for each index from a team hitting gameLog."""
    k_rows: list[tuple[str, int, int]] = []
    ob_rows: list[tuple[str, int, int]] = []
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
                ob = int(stat.get("hits")) + int(stat.get("baseOnBalls")) + int(stat.get("hitByPitch") or 0)
            except (TypeError, ValueError):
                continue
            raw_date = str(split.get("date") or "")[:10]
            if len(raw_date) != 10 or pa <= 0 or not (0 <= ks <= pa and 0 <= ob <= pa):
                continue
            k_rows.append((raw_date, ks, pa))
            ob_rows.append((raw_date, ob, pa))
    return {"kidx": sorted(k_rows), "obidx": sorted(ob_rows)}


def build_indices(team_rows: Mapping[tuple[int, int], Mapping[str, Sequence[tuple[str, int, int]]]]) -> dict[str, OppIndex]:
    return {name: OppIndex({key: rows[name] for key, rows in team_rows.items()}) for name in INDICES}


def adjusted_outs_mass_over(values: Sequence[float]) -> np.ndarray:
    """Fraction of mass above each outs threshold after linear floor/ceil split (clip [0, 27])."""
    if not values:
        raise OppOutsResearchError("empty history")
    hist = np.zeros(OUTS_MAX + 1)
    for x in values:
        x = min(max(float(x), 0.0), float(OUTS_MAX))
        lo = int(floor(x))
        frac = x - lo
        if lo >= OUTS_MAX:
            hist[OUTS_MAX] += 1.0
            continue
        hist[lo] += 1.0 - frac
        hist[lo + 1] += frac
    support = np.arange(OUTS_MAX + 1)
    return np.array([hist[support > t].sum() for t in OUTS_THRESH]) / len(values)


def factor(own: Sequence[OStart], target: OStart, index: OppIndex, beta: float) -> float:
    """Mean rescale factor applied to the history (card/diagnostic only)."""
    rt = index.rel(target.opp_id, target.season, target.date)
    return float(np.mean([(rt / index.rel(r.opp_id, r.season, r.date)) ** beta for r in own]))


def predict_outs(own: Sequence[OStart], target: OStart, indices: Mapping[str, OppIndex],
                 cand: tuple[str, float]) -> np.ndarray:
    """Engine-style P(over) at every outs threshold; the baseline is the production price."""
    if not own:
        raise OppOutsResearchError("needs own history")
    name, beta = cand
    if beta == 0:
        xs = [float(r.outs) for r in own]
    else:
        index = indices[name]
        rt = index.rel(target.opp_id, target.season, target.date)
        xs = [r.outs * (rt / index.rel(r.opp_id, r.season, r.date)) ** beta for r in own]
    return posterior_over(adjusted_outs_mass_over(xs), float(len(own)))


def evaluate(eval_starts: Sequence[OStart], window: Mapping[OStart, list[OStart]], indices: Mapping[str, OppIndex],
             candidates: Sequence[tuple[str, float]] = CANDIDATES) -> list[dict[str, Any]]:
    rows = []
    for s in eval_starts:
        prior = window.get(s, [])
        if len(prior) < MIN_PRODUCTION_STARTS:
            continue
        own = prior[-OWN_WINDOW:]
        rows.append({
            "pitcher_id": s.pitcher_id, "y_outs": s.outs,
            "rel": {n: indices[n].rel(s.opp_id, s.season, s.date) for n in indices},
            "preds": {c: predict_outs(own, s, indices, c) for c in candidates},
        })
    return rows


def rps_table(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, float], float]:
    if not rows:
        raise OppOutsResearchError("no rows")
    return {c: float(np.mean([rps(r["preds"][c], r["y_outs"], OUTS_THRESH) for r in rows])) for c in rows[0]["preds"]}


def select(table: Mapping[tuple[str, float], float], order: Sequence[tuple[str, float]] = CANDIDATES) -> tuple[str, float]:
    """Lowest RPS; ties go to the earlier candidate (baseline first)."""
    best, val = None, inf
    for c in order:
        if c in table and table[c] < val - 1e-12:
            best, val = c, table[c]
    if best is None:
        raise OppOutsResearchError("no candidate")
    return best


def cluster_bootstrap(rows: Sequence[Mapping[str, Any]], a, b, *, reps: int = 2000, seed: int = BOOT_SEED) -> dict[str, float]:
    clusters: dict[int, list[float]] = {}
    for r in rows:
        d = rps(r["preds"][a], r["y_outs"], OUTS_THRESH) - rps(r["preds"][b], r["y_outs"], OUTS_THRESH)
        clusters.setdefault(r["pitcher_id"], []).append(d)
    if not clusters:
        raise OppOutsResearchError("no paired rows")
    sums = np.array([sum(v) for v in clusters.values()])
    counts = np.array([len(v) for v in clusters.values()], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(sums), size=(reps, len(sums)))
    boots = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    return {"diff": float(sums.sum() / counts.sum()), "lo": float(np.quantile(boots, 0.025)),
            "hi": float(np.quantile(boots, 0.975)), "pitchers": float(len(sums)), "starts": float(counts.sum())}


def typical_metrics(rows: Sequence[Mapping[str, Any]], cand) -> dict[str, float]:
    ps, ys = [], []
    for r in rows:
        for line in TYPICAL_OUTS:
            i = int(np.where(np.isclose(OUTS_THRESH, line))[0][0])
            ps.append(float(r["preds"][cand][i]))
            ys.append(1.0 if r["y_outs"] > line else 0.0)
    if not ps:
        return {"n": 0.0, "logloss": float("nan"), "ece": float("nan")}
    p = np.clip(np.array(ps), 1e-6, 1 - 1e-6)
    y = np.array(ys)
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    bins = np.minimum((p * 10).astype(int), 9)
    ece = sum(float((bins == b).mean() * abs(p[bins == b].mean() - y[bins == b].mean())) for b in range(10) if (bins == b).any())
    return {"n": float(len(p)), "logloss": ll, "ece": float(ece)}


def ship_decision(test_rows: Sequence[Mapping[str, Any]], cand: tuple[str, float]) -> dict[str, Any]:
    rule1 = cand != BASELINE and cand[1] != 0
    boot = cluster_bootstrap(test_rows, cand, BASELINE) if rule1 else None
    base = typical_metrics(test_rows, BASELINE)
    sel = typical_metrics(test_rows, cand)
    rule2 = bool(boot and boot["hi"] < 0)
    rule3 = sel["ece"] <= base["ece"] + ECE_SLACK
    return {"candidate": label(cand), "bootstrap_vs_base": boot, "typical_base": base, "typical_selected": sel,
            "rule1_not_baseline": rule1, "rule2_beats_base": rule2, "rule3_calibrated": bool(rule3),
            "ships": bool(rule1 and rule2 and rule3)}
