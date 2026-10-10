"""Postseason bias check of the production PITCHER_K / PITCHER_OUTS prices (#1482).

Protocol: docs/MLB_POSTSEASON_PITCHER_PROP_BIAS_PREREG.md (pre-registered). Research
only: nothing here changes model_p. The prices are the production prices, reproduced
with the research ``predict_k`` / ``predict_outs`` functions that are parity-tested
against ``pitcher_joint_engine`` to 1e-12.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from sportsedge import mlb_opp_k_context as LANE_K
from sportsedge import mlb_opp_outs_context as LANE_O
from sportsedge.mlb_opp_k_context_research import KStart, OppIndex, predict_k
from sportsedge.mlb_opp_outs_context_research import OStart, predict_outs
from sportsedge.mlb_pitcher_prior_research import (
    K_THRESH,
    MIN_PRODUCTION_STARTS,
    OUTS_MAX,
    OUTS_THRESH,
    OWN_WINDOW,
    PriorResearchError,
    outs_from_ip,
)

PREREG_PATH = Path(__file__).resolve().parents[1] / "docs" / "MLB_POSTSEASON_PITCHER_PROP_BIAS_PREREG.md"
SEASONS = (2022, 2023, 2024, 2025)
UNSEEN_SEASON = 2022
POSTSEASON_TYPES = ("F", "D", "L", "W")
TYPICAL = {"PITCHER_K": (3.5, 4.5, 5.5, 6.5), "PITCHER_OUTS": (14.5, 15.5, 16.5, 17.5)}
MARKETS = ("PITCHER_K", "PITCHER_OUTS")
MIN_ABS_BIAS = 0.03
BOOT_REPS = 2000
BOOT_SEED = 20261010
EPS = 1e-12


class PostseasonBiasError(ValueError):
    pass


@dataclass(frozen=True)
class PStart:
    pitcher_id: int
    season: int
    date: str
    game_pk: int
    game_type: str
    team_id: int
    opp_id: int
    outs: int
    k: int


def prereg_sha256() -> str:
    return hashlib.sha256(PREREG_PATH.read_bytes()).hexdigest()


def _int(x: Any) -> int | None:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def final_postseason_games(payload: Mapping[str, Any]) -> list[tuple[int, str, str]]:
    """(gamePk, officialDate, gameType) for Final postseason games in a schedule payload."""
    out: dict[int, tuple[int, str, str]] = {}
    for block in payload.get("dates") or []:
        for g in (block or {}).get("games") or []:
            if not isinstance(g, Mapping):
                continue
            gt = str(g.get("gameType") or "")
            state = str((g.get("status") or {}).get("abstractGameState") or "")
            pk = _int(g.get("gamePk"))
            day = str(g.get("officialDate") or block.get("date") or "")[:10]
            if gt in POSTSEASON_TYPES and state == "Final" and pk and len(day) == 10:
                out[pk] = (pk, day, gt)
    return sorted(out.values(), key=lambda r: (r[1], r[0]))


def starters_from_boxscore(payload: Mapping[str, Any], *, game_pk: int, date: str, season: int,
                           game_type: str) -> list[PStart]:
    """Both starters (first listed pitcher per side) with outs and strikeouts."""
    teams = payload.get("teams") or {}
    ids: dict[str, int | None] = {s: _int(((teams.get(s) or {}).get("team") or {}).get("id")) for s in ("away", "home")}
    out: list[PStart] = []
    for side, other in (("away", "home"), ("home", "away")):
        box = teams.get(side) or {}
        pitchers = box.get("pitchers") or []
        if not pitchers or ids[side] is None or ids[other] is None:
            continue
        pid = _int(pitchers[0])
        row = (box.get("players") or {}).get(f"ID{pid}") or {}
        stat = ((row.get("stats") or {}).get("pitching")) or {}
        try:
            outs = outs_from_ip(stat.get("inningsPitched"))
            k = int(stat.get("strikeOuts"))
        except (TypeError, ValueError, PriorResearchError):
            continue
        if pid is None or not 0 <= outs <= OUTS_MAX or k < 0:
            continue
        out.append(PStart(pid, season, date, game_pk, game_type, int(ids[side]), int(ids[other]), outs, k))
    return out


def own_history(regular: Iterable[KStart], target: PStart) -> list[KStart]:
    """Production window: regular-season starts in Y-1..Y strictly before the date, last 10."""
    rows = sorted((r for r in regular if r.pitcher_id == target.pitcher_id and r.date < target.date
                   and r.season in (target.season - 1, target.season)), key=lambda r: (r.date, r.game_pk))
    return rows[-OWN_WINDOW:]


def lanes_allowed(team_games: Mapping[tuple[int, int], Sequence[Any]], season: int) -> bool:
    """Production refuses both lanes when any Y-2 / Y-1 team log is short (< 100 games)."""
    for s in (season - 2, season - 1):
        rows = [v for (_t, ss), v in team_games.items() if ss == s]
        if len(rows) != LANE_K.TEAMS_PER_SEASON or min(len(v) for v in rows) < LANE_K.MIN_PRIOR_SEASON_GAMES:
            return False
    return True


def season_indices(k_games: Mapping[tuple[int, int], Sequence[tuple[str, int, int]]],
                   ob_games: Mapping[tuple[int, int], Sequence[tuple[str, int, int]]], season: int):
    """Indices built from Y-2..Y only, as production does; None when production would refuse."""
    window = (season - 2, season - 1, season)
    if not (lanes_allowed(k_games, season) and lanes_allowed(ob_games, season)):
        return None
    kidx = OppIndex({key: v for key, v in k_games.items() if key[1] in window})
    obidx = OppIndex({key: v for key, v in ob_games.items() if key[1] in window})
    return kidx, obidx


def production_prices(own: Sequence[KStart], own_outs: Sequence[OStart], target: PStart, indices) -> dict[str, np.ndarray]:
    """Production P(over) at every half line for K and outs (lanes off -> beta 0)."""
    if len(own) < MIN_PRODUCTION_STARTS or len(own) != len(own_outs):
        raise PostseasonBiasError("needs >= 5 own starts")
    kt = KStart(target.pitcher_id, target.season, target.date, target.game_pk, target.team_id, target.opp_id, target.k)
    ot = OStart(target.pitcher_id, target.season, target.date, target.game_pk, target.team_id, target.opp_id, target.outs)
    if indices is None:
        pk = predict_k(own, kt, None, 0.0)  # type: ignore[arg-type]
        po = predict_outs(own_outs, ot, {}, ("base", 0.0))
    else:
        kidx, obidx = indices
        pk = predict_k(own, kt, kidx, LANE_K.BETA)
        po = predict_outs(own_outs, ot, {LANE_O.INDEX: obidx}, (LANE_O.INDEX, LANE_O.BETA))
    return {"PITCHER_K": pk, "PITCHER_OUTS": po}


def typical_pairs(market: str, p_over: np.ndarray, y: int) -> list[tuple[float, float]]:
    thresh = K_THRESH if market == "PITCHER_K" else OUTS_THRESH
    out = []
    for line in TYPICAL[market]:
        i = int(np.where(np.isclose(thresh, line))[0][0])
        out.append((float(p_over[i]), 1.0 if y > line else 0.0))
    return out


def _bias(rows: Sequence[Mapping[str, Any]], market: str) -> float:
    pairs = [pq for r in rows for pq in r["pairs"][market]]
    return float(np.mean([p - q for p, q in pairs])) if pairs else float("nan")


def bootstrap_bias(rows: Sequence[Mapping[str, Any]], market: str, *, reps: int = BOOT_REPS,
                   seed: int = BOOT_SEED) -> dict[str, float]:
    """Game-clustered percentile bootstrap of the over-bias."""
    by_game: dict[int, list[float]] = {}
    for r in rows:
        by_game.setdefault(r["game_pk"], []).extend(p - q for p, q in r["pairs"][market])
    games = sorted(by_game)
    sums = np.array([sum(by_game[g]) for g in games])
    cnts = np.array([len(by_game[g]) for g in games])
    rng = np.random.default_rng(seed)
    stats = np.empty(reps)
    for i in range(reps):
        idx = rng.integers(0, len(games), len(games))
        stats[i] = sums[idx].sum() / cnts[idx].sum()
    return {"bias": float(sums.sum() / cnts.sum()), "lo": float(np.quantile(stats, 0.025)),
            "hi": float(np.quantile(stats, 0.975)), "games": len(games)}


def info_metrics(rows: Sequence[Mapping[str, Any]], market: str) -> dict[str, float]:
    pairs = np.array([pq for r in rows for pq in r["pairs"][market]])
    if not len(pairs):
        return {}
    p, q = np.clip(pairs[:, 0], EPS, 1 - EPS), pairs[:, 1]
    bins = np.minimum((p * 10).astype(int), 9)
    ece = sum(abs(p[bins == b].mean() - q[bins == b].mean()) * (bins == b).sum() for b in range(10) if (bins == b).any()) / len(p)
    key = "y_k" if market == "PITCHER_K" else "y_outs"
    mkey = "mean_k" if market == "PITCHER_K" else "mean_outs"
    return {"brier": float(np.mean((p - q) ** 2)),
            "logloss": float(-np.mean(q * np.log(p) + (1 - q) * np.log(1 - p))),
            "ece": float(ece), "p_over_ge_half": float(np.mean(p >= 0.5)),
            "mean_own_last10": float(np.mean([r[mkey] for r in rows])), "mean_real": float(np.mean([r[key] for r in rows]))}


def decision(rows: Sequence[Mapping[str, Any]], market: str) -> dict[str, Any]:
    pooled = bootstrap_bias(rows, market)
    unseen = _bias([r for r in rows if r["season"] == UNSEEN_SEASON], market)
    r1 = pooled["lo"] > 0 or pooled["hi"] < 0
    r2 = abs(pooled["bias"]) >= MIN_ABS_BIAS
    r3 = bool(np.isfinite(unseen)) and np.sign(unseen) == np.sign(pooled["bias"]) and unseen != 0
    return {"pooled": pooled, "unseen_2022_bias": unseen,
            "per_season": {s: _bias([r for r in rows if r["season"] == s], market) for s in SEASONS},
            "rule1_ci_excludes_0": bool(r1), "rule2_material": bool(r2), "rule3_2022_same_sign": bool(r3),
            "guard": bool(r1 and r2 and r3)}


def build_rows(starts: Sequence[PStart], regular_k: Sequence[KStart], regular_o: Sequence[OStart],
               indices_by_season: Mapping[int, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    o_by_key = {(r.pitcher_id, r.date, r.game_pk): r for r in regular_o}
    by_pitcher: dict[int, list[KStart]] = {}
    for r in regular_k:
        by_pitcher.setdefault(r.pitcher_id, []).append(r)
    rows: list[dict[str, Any]] = []
    drops = {"thin_history": 0, "outs_mismatch": 0}
    for s in starts:
        own = own_history(by_pitcher.get(s.pitcher_id, []), s)
        if len(own) < MIN_PRODUCTION_STARTS:
            drops["thin_history"] += 1
            continue
        own_o = [o_by_key.get((r.pitcher_id, r.date, r.game_pk)) for r in own]
        if any(o is None for o in own_o):
            drops["outs_mismatch"] += 1
            continue
        prices = production_prices(own, own_o, s, indices_by_season.get(s.season))
        rows.append({"season": s.season, "game_pk": s.game_pk, "game_type": s.game_type, "pitcher_id": s.pitcher_id,
                     "y_k": s.k, "y_outs": s.outs,
                     "mean_k": float(np.mean([r.k for r in own])), "mean_outs": float(np.mean([o.outs for o in own_o])),
                     "pairs": {m: typical_pairs(m, prices[m], s.k if m == "PITCHER_K" else s.outs) for m in MARKETS}})
    return rows, drops


__all__ = ["PStart", "MARKETS", "SEASONS", "build_rows", "decision", "final_postseason_games", "info_metrics",
           "lanes_allowed", "prereg_sha256", "production_prices", "season_indices", "starters_from_boxscore"]
