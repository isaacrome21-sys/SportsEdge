"""Held-out check of the frozen few-starts fallback on PITCHER_BB / HITS_ALLOWED / ER.

Protocol: docs/MLB_PITCHER_PRIOR_FALLBACK_EXT_PREREG.md (pre-registered). Research
only: never imported by production engines, changes no model_p. The candidate is the
production #1495/#1500 fallback (league_short pool, m = 4, n = k + m) with no tuning.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from sportsedge import mlb_pitcher_prior_research as R

PREREG_PATH = Path(__file__).resolve().parents[1] / "docs" / "MLB_PITCHER_PRIOR_FALLBACK_EXT_PREREG.md"
POOL = "league_short"
M = 4.0
SEED = 20261010
STATS = ("bb", "h", "er")
CAPS = {"bb": 10, "h": 15, "er": 12}
THRESH = {s: np.arange(0, CAPS[s]) + 0.5 for s in STATS}
TYPICAL = {"bb": (0.5, 1.5, 2.5), "h": (2.5, 3.5, 4.5, 5.5), "er": (0.5, 1.5, 2.5)}
MARKET = {"bb": "PITCHER_BB", "h": "PITCHER_HITS_ALLOWED", "er": "PITCHER_ER"}


class ExtResearchError(ValueError):
    pass


@dataclass(frozen=True)
class XStart:
    pitcher_id: int
    season: int
    date: str
    game_pk: int
    team_id: int
    outs: int
    k: int
    bb: int
    h: int
    er: int


def prereg_sha256() -> str:
    return hashlib.sha256(PREREG_PATH.read_bytes()).hexdigest()


def starts_from_gamelog(payload: Mapping[str, Any], *, pitcher_id: int, season: int) -> list[XStart]:
    """Same start filter as #1495 (gamesStarted >= 1, valid IP/date/team) plus BB/H/ER."""
    out: list[XStart] = []
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
                outs = R.outs_from_ip(stat.get("inningsPitched"))
                ks = int(stat.get("strikeOuts", 0) or 0)
                bb = int(stat.get("baseOnBalls", 0) or 0)
                h = int(stat.get("hits", 0) or 0)
                er = int(stat.get("earnedRuns", 0) or 0)
            except (TypeError, ValueError, R.PriorResearchError):
                continue
            if not 0 <= outs <= R.OUTS_MAX or min(ks, bb, h, er) < 0:
                continue
            raw_date = str(split.get("date") or "")[:10]
            if len(raw_date) != 10:
                continue
            try:
                team_id = int((split.get("team") or {}).get("id"))
            except (TypeError, ValueError):
                continue
            game = split.get("game") or {}
            out.append(XStart(int(pitcher_id), int(season), raw_date, int(game.get("gamePk") or 0), team_id, outs, ks, bb, h, er))
    return out


def _over_frac(values: Sequence[int], stat: str) -> np.ndarray:
    return R._over_frac(R._hist(values, CAPS[stat]), THRESH[stat])


def league_short_pool(prior_season_starts: Sequence[XStart], window: Mapping[XStart, list[XStart]]) -> dict[str, np.ndarray]:
    short = [s for s in prior_season_starts if len(window.get(s, ())) < R.MIN_PRODUCTION_STARTS]
    if len(short) < 100:
        raise ExtResearchError(f"league_short pool too small: {len(short)}")
    return {stat: _over_frac([getattr(r, stat) for r in short], stat) for stat in STATS}


def predict_own(own: Sequence[XStart]) -> dict[str, np.ndarray]:
    k = len(own)
    if k < 1:
        raise ExtResearchError("own-only needs k>=1")
    return {stat: R.posterior_over(_over_frac([getattr(r, stat) for r in own], stat), float(k)) for stat in STATS}


def predict_fallback(own: Sequence[XStart], prior: Mapping[str, np.ndarray], m: float = M) -> dict[str, np.ndarray]:
    """Production fallback: over = (own_over*k + prior_over*m)/(k+m), Jeffreys with n = k+m."""
    k = len(own)
    out = {}
    for stat in STATS:
        mass = prior[stat] * m if k == 0 else _over_frac([getattr(r, stat) for r in own], stat) * k + prior[stat] * m
        out[stat] = R.posterior_over(mass / (k + m), k + m)
    return out


def rps(p_over: np.ndarray, y: int, stat: str) -> float:
    return float(((p_over - (y > THRESH[stat]).astype(float)) ** 2).sum())


def evaluate(eval_starts: Sequence[XStart], window: Mapping[XStart, list[XStart]], prior: Mapping[str, np.ndarray], *, ks: Iterable[int]) -> list[dict[str, Any]]:
    ks = set(ks)
    rows = []
    for s in eval_starts:
        hist = window.get(s, [])
        if len(hist) not in ks:
            continue
        own = hist[-R.OWN_WINDOW:]
        preds = {"fallback": predict_fallback(own, prior)}
        if own:
            preds["own"] = predict_own(own)
        rows.append({"pitcher_id": s.pitcher_id, "k": len(own), "y": {st: getattr(s, st) for st in STATS}, "preds": preds})
    return rows


def reference_rows(eval_starts: Sequence[XStart], window: Mapping[XStart, list[XStart]]) -> list[dict[str, Any]]:
    rows = []
    for s in eval_starts:
        hist = window.get(s, [])
        if len(hist) < R.MIN_PRODUCTION_STARTS:
            continue
        rows.append({"pitcher_id": s.pitcher_id, "k": len(hist), "y": {st: getattr(s, st) for st in STATS}, "preds": {"own": predict_own(hist[-R.OWN_WINDOW:])}})
    return rows


def mean_rps(rows: Sequence[Mapping[str, Any]], name: str, stat: str) -> float:
    vals = [rps(r["preds"][name][stat], r["y"][stat], stat) for r in rows if name in r["preds"]]
    return float(np.mean(vals)) if vals else float("nan")


def cluster_bootstrap_diff(rows: Sequence[Mapping[str, Any]], a: str, b: str, stat: str, *, reps: int = 2000, seed: int = SEED) -> dict[str, float]:
    clusters: dict[int, list[float]] = {}
    for r in rows:
        if a in r["preds"] and b in r["preds"]:
            clusters.setdefault(r["pitcher_id"], []).append(rps(r["preds"][a][stat], r["y"][stat], stat) - rps(r["preds"][b][stat], r["y"][stat], stat))
    if not clusters:
        raise ExtResearchError("no paired rows")
    sums = np.array([sum(v) for v in clusters.values()])
    counts = np.array([len(v) for v in clusters.values()], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(sums), size=(reps, len(sums)))
    boots = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    return {"diff": float(sums.sum() / counts.sum()), "lo": float(np.quantile(boots, 0.025)), "hi": float(np.quantile(boots, 0.975)),
            "pitchers": float(len(sums)), "starts": float(counts.sum())}


def typical_line_metrics(rows: Sequence[Mapping[str, Any]], name: str, stat: str) -> dict[str, float]:
    ps, ys = [], []
    for r in rows:
        if name not in r["preds"]:
            continue
        for line in TYPICAL[stat]:
            i = int(np.where(np.isclose(THRESH[stat], line))[0][0])
            ps.append(float(r["preds"][name][stat][i]))
            ys.append(1.0 if r["y"][stat] > line else 0.0)
    if not ps:
        return {"n": 0.0, "logloss": float("nan"), "ece": float("nan")}
    p = np.clip(np.array(ps), 1e-6, 1 - 1e-6)
    y = np.array(ys)
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    bins = np.minimum((p * 10).astype(int), 9)
    ece = sum(float((bins == b).mean()) * abs(float(p[bins == b].mean()) - float(y[bins == b].mean())) for b in range(10) if (bins == b).any())
    return {"n": float(len(p)), "logloss": ll, "ece": float(ece)}


def ship_decision(test_rows, consistency_rows, ref_rows) -> dict[str, Any]:
    out: dict[str, Any] = {"pool": POOL, "m": M, "markets": {}}
    for stat in STATS:
        boot = cluster_bootstrap_diff(test_rows, "fallback", "own", stat)
        cons = cluster_bootstrap_diff(consistency_rows, "fallback", "own", stat)
        fb = typical_line_metrics(test_rows, "fallback", stat)
        own = typical_line_metrics(test_rows, "own", stat)
        ref = typical_line_metrics(ref_rows, "own", stat)
        ece_cap = max(0.03, ref["ece"] + 0.01)
        rule1 = boot["hi"] < 0
        rule2 = fb["ece"] <= ece_cap
        rule3 = cons["diff"] < 0
        out["markets"][MARKET[stat]] = {
            "test_vs_own": boot, "consistency_vs_own": cons, "fallback_typical": fb, "own_typical": own,
            "reference_typical": ref, "ece_cap": ece_cap,
            "rule1_beats_own_2025": rule1, "rule2_calibrated_2025": rule2, "rule3_sign_2024": rule3,
            "ships": bool(rule1 and rule2 and rule3),
        }
    return out
