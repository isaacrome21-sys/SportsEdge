"""Postseason bias check of the production PITCHER_BB / HITS_ALLOWED / ER / HITS_WALKS_ER prices (#1482).

Protocol: docs/MLB_POSTSEASON_PITCHER_PROP_BIAS_EXT_PREREG.md (pre-registered). Research
only: nothing here changes model_p. Prices come from ``pitcher_joint_engine`` itself, fed
the features ``mlb_generic_features`` builds for the k >= 5 path (UMP-BB lane off).
The bootstrap and decision rule are the #1967 / #1968 code path, unchanged.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from sportsedge import mlb_postseason_prop_bias_research as BASE
from sportsedge.mlb_pitcher_prior_ext_research import XStart
from sportsedge.mlb_pitcher_prior_research import MIN_PRODUCTION_STARTS, OUTS_MAX, OWN_WINDOW, PriorResearchError, outs_from_ip
from sportsedge.pitcher_joint_engine import price_pitcher_market

PREREG_PATH = Path(__file__).resolve().parents[1] / "docs" / "MLB_POSTSEASON_PITCHER_PROP_BIAS_EXT_PREREG.md"
SEASONS = BASE.SEASONS
UNSEEN_SEASON = BASE.UNSEEN_SEASON
POSTSEASON_TYPES = BASE.POSTSEASON_TYPES
MARKETS = ("PITCHER_BB", "PITCHER_HITS_ALLOWED", "PITCHER_ER", "PITCHER_HITS_WALKS_ER")
TYPICAL = {
    "PITCHER_BB": (0.5, 1.5, 2.5),
    "PITCHER_HITS_ALLOWED": (2.5, 3.5, 4.5, 5.5),
    "PITCHER_ER": (0.5, 1.5, 2.5),
    "PITCHER_HITS_WALKS_ER": (2.5, 4.5, 6.5, 8.5, 10.5),
}
PRIOR_POOL_MARKETS = frozenset({"PITCHER_HITS_ALLOWED", "PITCHER_ER", "PITCHER_HITS_WALKS_ER"})
PRIOR_SPAN = 30
MIN_PRIOR_ROWS = 5
MIN_ABS_BIAS = BASE.MIN_ABS_BIAS
BOOT_REPS = BASE.BOOT_REPS
BOOT_SEED = BASE.BOOT_SEED
EPS = 1e-12


class PostseasonBiasExtError(ValueError):
    pass


@dataclass(frozen=True)
class PStartX:
    pitcher_id: int
    season: int
    date: str
    game_pk: int
    game_type: str
    team_id: int
    opp_id: int
    outs: int
    k: int
    bb: int
    h: int
    er: int


def prereg_sha256() -> str:
    return hashlib.sha256(PREREG_PATH.read_bytes()).hexdigest()


def _int(x: Any) -> int | None:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def starters_from_boxscore(payload: Mapping[str, Any], *, game_pk: int, date: str, season: int,
                           game_type: str) -> list[PStartX]:
    """Both starters (first listed pitcher per side) with outs, K, BB, H and ER."""
    teams = payload.get("teams") or {}
    ids = {s: _int(((teams.get(s) or {}).get("team") or {}).get("id")) for s in ("away", "home")}
    out: list[PStartX] = []
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
            k, bb, h, er = (int(stat.get(key)) for key in ("strikeOuts", "baseOnBalls", "hits", "earnedRuns"))
        except (TypeError, ValueError, PriorResearchError):
            continue
        if pid is None or not 0 <= outs <= OUTS_MAX or min(k, bb, h, er) < 0:
            continue
        out.append(PStartX(pid, season, date, game_pk, game_type, int(ids[side]), int(ids[other]), outs, k, bb, h, er))
    return out


def regular_window(regular: Iterable[XStart], target: PStartX) -> list[XStart]:
    """Production ``player_rows``: seasons Y-1..Y, strictly before the date, stable date sort."""
    rows = [r for r in regular if r.pitcher_id == target.pitcher_id and r.date < target.date
            and r.season in (target.season - 1, target.season)]
    rows.sort(key=lambda r: r.season)  # Y-1 block, then Y block; gamelog order kept inside (stable)
    rows.sort(key=lambda r: r.date)  # production: rows.sort(key=date), stable
    return rows


def own_and_prior(window: Sequence[XStart]) -> tuple[list[XStart], list[XStart] | None]:
    """Production split: last <=10 starts; prior pool = starts 11..30 back when >= 5 of them."""
    own = list(window[-OWN_WINDOW:])
    older = list(window[-PRIOR_SPAN:-OWN_WINDOW]) if len(window) > OWN_WINDOW else []
    return own, (older if len(older) >= MIN_PRIOR_ROWS else None)


def joint_row(s: XStart | PStartX) -> dict[str, int]:
    return {"strikeouts": s.k, "outs": s.outs, "earned_runs": s.er, "hits_allowed": s.h, "walks_allowed": s.bb}


def realised(s: PStartX, market: str) -> int:
    if market == "PITCHER_BB":
        return s.bb
    if market == "PITCHER_HITS_ALLOWED":
        return s.h
    if market == "PITCHER_ER":
        return s.er
    if market == "PITCHER_HITS_WALKS_ER":
        return s.h + s.bb + s.er
    raise PostseasonBiasExtError(f"unknown market {market}")


def production_features(own: Sequence[XStart], prior: Sequence[XStart] | None, market: str) -> dict[str, Any]:
    if len(own) < MIN_PRODUCTION_STARTS:
        raise PostseasonBiasExtError("needs >= 5 own starts")
    features: dict[str, Any] = {"history_pool": [joint_row(r) for r in own]}
    if market in PRIOR_POOL_MARKETS and prior:
        features["prior_pool"] = [joint_row(r) for r in prior]
    return features


def production_p_over(own: Sequence[XStart], prior: Sequence[XStart] | None, market: str, line: float) -> float:
    """model_p for OVER from the production engine (k >= 5 path, UMP-BB lane off)."""
    out = price_pitcher_market({"game_id": "research", "market": market, "entity_id": "research", "line": line,
                                "side": "OVER", "features": production_features(own, prior, market)})
    return float(out["model_p"])


def realised_x(r: XStart, market: str) -> int:
    return realised(PStartX(r.pitcher_id, r.season, r.date, r.game_pk, "R", r.team_id, 0, r.outs, r.k, r.bb, r.h, r.er), market)


def build_rows(starts: Sequence[PStartX], regular: Sequence[XStart]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    by_pitcher: dict[int, list[XStart]] = {}
    for r in regular:
        by_pitcher.setdefault(r.pitcher_id, []).append(r)
    rows: list[dict[str, Any]] = []
    drops = {"thin_history": 0}
    for s in starts:
        own, prior = own_and_prior(regular_window(by_pitcher.get(s.pitcher_id, []), s))
        if len(own) < MIN_PRODUCTION_STARTS:
            drops["thin_history"] += 1
            continue
        pairs = {m: [(production_p_over(own, prior, m, line), 1.0 if realised(s, m) > line else 0.0) for line in TYPICAL[m]]
                 for m in MARKETS}
        rows.append({"season": s.season, "game_pk": s.game_pk, "game_type": s.game_type, "pitcher_id": s.pitcher_id,
                     "has_prior_pool": prior is not None,
                     "y": {m: realised(s, m) for m in MARKETS},
                     "mean_own": {m: float(np.mean([realised_x(r, m) for r in own])) for m in MARKETS},
                     "pairs": pairs})
    return rows, drops


def decision(rows: Sequence[Mapping[str, Any]], market: str) -> dict[str, Any]:
    """The #1967 rule, unchanged (bootstrap, materiality, 2022 sign)."""
    return BASE.decision(rows, market)


def info_metrics(rows: Sequence[Mapping[str, Any]], market: str) -> dict[str, float]:
    pairs = np.array([pq for r in rows for pq in r["pairs"][market]])
    if not len(pairs):
        return {}
    p, q = np.clip(pairs[:, 0], EPS, 1 - EPS), pairs[:, 1]
    bins = np.minimum((p * 10).astype(int), 9)
    ece = sum(abs(p[bins == b].mean() - q[bins == b].mean()) * (bins == b).sum() for b in range(10) if (bins == b).any()) / len(p)
    return {"brier": float(np.mean((p - q) ** 2)),
            "logloss": float(-np.mean(q * np.log(p) + (1 - q) * np.log(1 - p))),
            "ece": float(ece), "p_over_ge_half": float(np.mean(p >= 0.5)),
            "mean_own_last10": float(np.mean([r["mean_own"][market] for r in rows])),
            "mean_real": float(np.mean([r["y"][market] for r in rows]))}


__all__ = ["MARKETS", "PStartX", "SEASONS", "TYPICAL", "build_rows", "decision", "info_metrics", "own_and_prior",
           "prereg_sha256", "production_features", "production_p_over", "regular_window", "starters_from_boxscore"]
