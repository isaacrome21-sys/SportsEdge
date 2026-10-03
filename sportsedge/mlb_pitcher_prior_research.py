"""Held-out validation of a few-starts pitcher fallback (prior pool shrinkage).

Protocol: docs/MLB_PITCHER_PRIOR_FALLBACK_PREREG.md (pre-registered). This module is
research only. It never changes model_p in production; it scores candidate
fallbacks against realised starts so a decision can be made from held-out data.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from math import inf, log
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

PREREG_PATH = Path(__file__).resolve().parents[1] / "docs" / "MLB_PITCHER_PRIOR_FALLBACK_PREREG.md"
JEFFREYS_ALPHA = 0.5
OUTS_MAX = 27
K_CAP = 20  # values >= 20 are clipped; the highest scored line is 19.5
OUTS_THRESH = np.arange(0, 27) + 0.5
K_THRESH = np.arange(0, 20) + 0.5
TYPICAL = {"outs": (14.5, 15.5, 16.5, 17.5), "k": (3.5, 4.5, 5.5, 6.5)}
POOLS = ("league_all", "league_short", "team_all")
M_GRID = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0, inf)
PRIOR_ONLY_N = 32.0
MIN_PRODUCTION_STARTS = 5
OWN_WINDOW = 10


class PriorResearchError(ValueError):
    pass


@dataclass(frozen=True)
class Start:
    pitcher_id: int
    season: int
    date: str  # ISO date
    game_pk: int
    team_id: int
    outs: int
    k: int


def prereg_sha256() -> str:
    return hashlib.sha256(PREREG_PATH.read_bytes()).hexdigest()


def outs_from_ip(value: Any) -> int:
    text = str(value).strip()
    if not text:
        raise PriorResearchError("inningsPitched missing")
    if "." not in text:
        return int(text) * 3
    whole, frac = text.split(".", 1)
    if frac not in {"0", "1", "2"}:
        raise PriorResearchError("inningsPitched invalid")
    return int(whole) * 3 + int(frac)


def starts_from_gamelog(payload: Mapping[str, Any], *, pitcher_id: int, season: int) -> list[Start]:
    """Regular-season starts (gamesStarted >= 1) from a StatsAPI pitching gameLog."""
    out: list[Start] = []
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
                ks = int(stat.get("strikeOuts", 0) or 0)
            except (TypeError, ValueError, PriorResearchError):
                continue
            if not 0 <= outs <= OUTS_MAX or ks < 0:
                continue
            raw_date = str(split.get("date") or "")[:10]
            if len(raw_date) != 10:
                continue
            team = split.get("team") or {}
            game = split.get("game") or {}
            try:
                team_id = int(team.get("id"))
            except (TypeError, ValueError):
                continue
            out.append(Start(int(pitcher_id), int(season), raw_date, int(game.get("gamePk") or 0), team_id, outs, ks))
    return out


def _key(s: Start) -> tuple[str, int]:
    return (s.date, s.game_pk)


def prior_window_counts(starts: Iterable[Start]) -> dict[Start, list[Start]]:
    """Map each start to the pitcher's strictly-earlier starts in seasons Y-1 and Y (production window)."""
    by_pitcher: dict[int, list[Start]] = {}
    for s in starts:
        by_pitcher.setdefault(s.pitcher_id, []).append(s)
    result: dict[Start, list[Start]] = {}
    for rows in by_pitcher.values():
        rows.sort(key=_key)
        for s in rows:
            result[s] = [r for r in rows if r.date < s.date and r.season in (s.season - 1, s.season)]
    return result


def _hist(values: Sequence[int], size: int) -> np.ndarray:
    h = np.zeros(size + 1)
    for v in values:
        h[min(int(v), size)] += 1
    return h


def _over_frac(hist: np.ndarray, thresholds: np.ndarray) -> np.ndarray:
    total = hist.sum()
    if total <= 0:
        raise PriorResearchError("empty pool")
    support = np.arange(hist.size)
    return np.array([hist[support > t].sum() for t in thresholds]) / total


def posterior_over(mass_over: np.ndarray, n: float) -> np.ndarray:
    """Production Jeffreys posterior for half-integer lines (over/under only)."""
    return (JEFFREYS_ALPHA + n * mass_over) / (2 * JEFFREYS_ALPHA + n)


@dataclass
class Pools:
    league_all: dict[str, np.ndarray]
    league_short: dict[str, np.ndarray]
    team_all: dict[int, dict[str, np.ndarray]]


def build_pools(prior_season_starts: Sequence[Start], window: Mapping[Start, list[Start]]) -> Pools:
    def frac(rows: Sequence[Start]) -> dict[str, np.ndarray]:
        return {
            "outs": _over_frac(_hist([r.outs for r in rows], OUTS_MAX), OUTS_THRESH),
            "k": _over_frac(_hist([r.k for r in rows], K_CAP), K_THRESH),
        }
    if not prior_season_starts:
        raise PriorResearchError("no prior-season starts")
    short = [s for s in prior_season_starts if len(window.get(s, ())) < MIN_PRODUCTION_STARTS]
    teams: dict[int, list[Start]] = {}
    for s in prior_season_starts:
        teams.setdefault(s.team_id, []).append(s)
    return Pools(frac(prior_season_starts), frac(short or prior_season_starts), {t: frac(r) for t, r in teams.items()})


def _prior(pools: Pools, name: str, team_id: int) -> dict[str, np.ndarray]:
    if name == "league_all":
        return pools.league_all
    if name == "league_short":
        return pools.league_short
    if name == "team_all":
        return pools.team_all.get(team_id, pools.league_all)
    raise PriorResearchError(name)


def predict(own: Sequence[Start], prior: Mapping[str, np.ndarray] | None, m: float) -> dict[str, np.ndarray]:
    """Engine-style P(over) at every scored threshold. prior None/m=0 -> own-only."""
    k = len(own)
    out: dict[str, np.ndarray] = {}
    for stat, thresholds, cap in (("outs", OUTS_THRESH, OUTS_MAX), ("k", K_THRESH, K_CAP)):
        own_frac = _over_frac(_hist([getattr(r, stat) for r in own], cap), thresholds) if k else None
        if prior is None or m == 0:
            if own_frac is None:
                raise PriorResearchError("own-only needs k>=1")
            out[stat] = posterior_over(own_frac, float(k))
        elif m == inf:
            out[stat] = posterior_over(prior[stat], PRIOR_ONLY_N)
        else:
            mass = prior[stat] * m if own_frac is None else own_frac * k + prior[stat] * m
            out[stat] = posterior_over(mass / (k + m), k + m)
    return out


def rps(p_over: np.ndarray, y: int, thresholds: np.ndarray) -> float:
    return float(((p_over - (y > thresholds).astype(float)) ** 2).sum())


def evaluate(eval_starts: Sequence[Start], window: Mapping[Start, list[Start]], pools: Pools, *, ks: Iterable[int]) -> dict[str, Any]:
    """Per-start scores for own-only and every (pool, m) candidate."""
    ks = set(ks)
    units = [s for s in eval_starts if len(window.get(s, ())) in ks]
    rows: list[dict[str, Any]] = []
    for s in units:
        own = window[s][-OWN_WINDOW:]
        row: dict[str, Any] = {"pitcher_id": s.pitcher_id, "k": len(own), "y_outs": s.outs, "y_k": s.k, "preds": {}}
        if own:
            row["preds"]["own"] = predict(own, None, 0)
        for pool in POOLS:
            prior = _prior(pools, pool, s.team_id)
            for m in M_GRID:
                row["preds"][f"{pool}|{m:g}"] = predict(own, prior, m)
        rows.append(row)
    return {"rows": rows}


def score_table(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, float]]:
    names = sorted({n for r in rows for n in r["preds"]})
    table: dict[str, dict[str, float]] = {}
    for name in names:
        sub = [r for r in rows if name in r["preds"]]
        if not sub:
            continue
        table[name] = {
            "n": float(len(sub)),
            "rps_outs": float(np.mean([rps(r["preds"][name]["outs"], r["y_outs"], OUTS_THRESH) for r in sub])),
            "rps_k": float(np.mean([rps(r["preds"][name]["k"], r["y_k"], K_THRESH) for r in sub])),
        }
    return table


def select(table: Mapping[str, Mapping[str, float]]) -> str:
    base = table["own"]
    best, best_val = None, inf
    for name, t in table.items():
        if name == "own":
            continue
        val = 0.5 * (t["rps_outs"] / base["rps_outs"] + t["rps_k"] / base["rps_k"])
        if val < best_val - 1e-12:
            best, best_val = name, val
    if best is None:
        raise PriorResearchError("no candidate")
    return best


def cluster_bootstrap_diff(rows: Sequence[Mapping[str, Any]], a: str, b: str, stat: str, *, reps: int = 2000, seed: int = 20261003) -> dict[str, float]:
    """Mean RPS(a) - RPS(b), with a pitcher-clustered bootstrap 95% CI."""
    thresholds = OUTS_THRESH if stat == "outs" else K_THRESH
    ykey = "y_outs" if stat == "outs" else "y_k"
    clusters: dict[int, list[float]] = {}
    for r in rows:
        if a in r["preds"] and b in r["preds"]:
            d = rps(r["preds"][a][stat], r[ykey], thresholds) - rps(r["preds"][b][stat], r[ykey], thresholds)
            clusters.setdefault(r["pitcher_id"], []).append(d)
    if not clusters:
        raise PriorResearchError("no paired rows")
    sums = np.array([sum(v) for v in clusters.values()])
    counts = np.array([len(v) for v in clusters.values()], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(sums), size=(reps, len(sums)))
    boots = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    return {"diff": float(sums.sum() / counts.sum()), "lo": float(np.quantile(boots, 0.025)), "hi": float(np.quantile(boots, 0.975)), "pitchers": float(len(sums)), "starts": float(counts.sum())}


def typical_line_metrics(rows: Sequence[Mapping[str, Any]], name: str, stat: str) -> dict[str, float]:
    thresholds = OUTS_THRESH if stat == "outs" else K_THRESH
    ykey = "y_outs" if stat == "outs" else "y_k"
    ps: list[float] = []
    ys: list[float] = []
    for r in rows:
        if name not in r["preds"]:
            continue
        for line in TYPICAL[stat]:
            i = int(np.where(np.isclose(thresholds, line))[0][0])
            ps.append(float(r["preds"][name][stat][i]))
            ys.append(1.0 if r[ykey] > line else 0.0)
    if not ps:
        return {"n": 0.0, "logloss": float("nan"), "ece": float("nan")}
    p = np.clip(np.array(ps), 1e-6, 1 - 1e-6)
    y = np.array(ys)
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    bins = np.minimum((p * 10).astype(int), 9)
    ece = 0.0
    for b in range(10):
        mask = bins == b
        if mask.any():
            ece += mask.mean() * abs(p[mask].mean() - y[mask].mean())
    return {"n": float(len(p)), "logloss": ll, "ece": float(ece)}


def reference_rows(eval_starts: Sequence[Start], window: Mapping[Start, list[Start]]) -> list[dict[str, Any]]:
    """Production own-only (last 10) on k>=5 starts: the accuracy production already accepts."""
    rows = []
    for s in eval_starts:
        prior = window.get(s, [])
        if len(prior) < MIN_PRODUCTION_STARTS:
            continue
        own = prior[-OWN_WINDOW:]
        rows.append({"pitcher_id": s.pitcher_id, "k": len(prior), "y_outs": s.outs, "y_k": s.k, "preds": {"own": predict(own, None, 0)}})
    return rows


def ship_decision(test_rows, selected: str, ref_rows) -> dict[str, Any]:
    out: dict[str, Any] = {"selected": selected, "checks": {}}
    ok = True
    for stat in ("outs", "k"):
        boot = cluster_bootstrap_diff(test_rows, selected, "own", stat)
        fb = typical_line_metrics(test_rows, selected, stat)
        ref = typical_line_metrics(ref_rows, "own", stat)
        rule1 = boot["hi"] < 0
        ece_cap = max(0.03, ref["ece"] + 0.01)
        rule2 = fb["ece"] <= ece_cap
        ok = ok and rule1 and rule2
        out["checks"][stat] = {"bootstrap_vs_own": boot, "fallback_typical": fb, "reference_typical": ref, "ece_cap": ece_cap, "rule1_beats_own": rule1, "rule2_calibrated": rule2}
    out["ships"] = bool(ok)
    return out
