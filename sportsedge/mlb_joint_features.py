"""Shared point-in-time feature builder for coherent MLB joint prop engines.

Recent rows remain the primary sample. Older strictly-prior rows are carried as a
separate capped empirical prior so the pricing engines can stabilize thin tails
without letting career history overwhelm current form. Sportsbook prices are never
feature inputs.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from math import exp, sqrt
from statistics import fmean
from typing import Any, Mapping, Sequence

from .mlb_generic_features import MLBGenericHistorySource, _number, _outs_from_ip
from .mlb_total_bases_features import park_factor_for_venue

FEATURE_VERSION = "mlb_joint_features_v6_long_window_prior"


class MLBJointFeatureError(ValueError):
    pass


def _sha(v: Any) -> str:
    raw = json.dumps(v, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def _tilt(weights: list[float], pool: list[dict[str, int]], field: str, target: float) -> list[float]:
    xs = [float(r[field]) for r in pool]
    lo_x, hi_x = min(xs), max(xs)
    if hi_x - lo_x < 1e-12:
        return weights
    target = min(hi_x - 1e-6, max(lo_x + 1e-6, target))
    lo, hi = -8.0, 8.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        raw = [w * exp(mid * x) for w, x in zip(weights, xs)]
        z = sum(raw)
        mean = sum(w * x for w, x in zip(raw, xs)) / z
        if mean < target:
            lo = mid
        else:
            hi = mid
    theta = (lo + hi) / 2.0
    raw = [w * exp(theta * x) for w, x in zip(weights, xs)]
    z = sum(raw)
    return [w / z for w in raw]


def _hitter_pool(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, int]]:
    pool: list[dict[str, int]] = []
    for row in rows:
        s = row["stat"]
        pa = int(_number(s.get("plateAppearances", 0), "plateAppearances"))
        if pa <= 0:
            continue
        hits = int(_number(s.get("hits", 0), "hits"))
        doubles = int(_number(s.get("doubles", 0), "doubles"))
        triples = int(_number(s.get("triples", 0), "triples"))
        hr = int(_number(s.get("homeRuns", 0), "homeRuns"))
        singles = hits - doubles - triples - hr
        if singles < 0:
            raise MLBJointFeatureError("historical batter row has negative singles")
        pool.append({
            "plate_appearances": pa,
            "hits": hits,
            "singles": singles,
            "doubles": doubles,
            "triples": triples,
            "home_runs": hr,
            "total_bases": singles + 2 * doubles + 3 * triples + 4 * hr,
            "rbi": int(_number(s.get("rbi", 0), "rbi")),
            "runs": int(_number(s.get("runs", 0), "runs")),
            "stolen_bases": int(_number(s.get("stolenBases", 0), "stolenBases")),
            "walks": int(_number(s.get("baseOnBalls", 0), "baseOnBalls")),
            "strikeouts": int(_number(s.get("strikeOuts", 0), "strikeOuts")),
            "extra_base_hits": doubles + triples + hr,
        })
    return pool


def _pitcher_pool(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, int]]:
    pool: list[dict[str, int]] = []
    for row in rows:
        s = row["stat"]
        vals = {
            "strikeouts": int(_number(s.get("strikeOuts", 0), "strikeOuts")),
            "outs": int(_outs_from_ip(s.get("inningsPitched"))),
            "earned_runs": int(_number(s.get("earnedRuns", 0), "earnedRuns")),
            "hits_allowed": int(_number(s.get("hits", 0), "hits")),
            "walks_allowed": int(_number(s.get("baseOnBalls", 0), "baseOnBalls")),
        }
        if not 0 <= vals["outs"] <= 27:
            raise MLBJointFeatureError("historical outs outside [0,27]")
        pool.append(vals)
    return pool


def build_hitter_joint_features(
    source: MLBGenericHistorySource,
    *,
    batter_id: int,
    target_date: date,
    opposing_pitcher_id: int,
    venue_id: int,
    window: int = 30,
) -> dict[str, Any]:
    all_batting = source.player_rows(
        player_id=batter_id, group="hitting", target_date=target_date
    )
    batting = all_batting[-window:]
    prior_batting = all_batting[-2 * window:-window]
    pool = _hitter_pool(batting)
    prior_pool = _hitter_pool(prior_batting)
    if len(pool) < 10:
        raise MLBJointFeatureError(f"batter history insufficient {len(pool)}<10")
    if len(prior_pool) < 10:
        prior_pool = []

    pitching = source.player_rows(
        player_id=opposing_pitcher_id, group="pitching", target_date=target_date
    )
    starts = [
        r for r in pitching
        if _number(r["stat"].get("gamesStarted", 0), "gamesStarted") >= 1
    ][-10:]
    if len(starts) < 5:
        raise MLBJointFeatureError(f"opposing pitcher history insufficient {len(starts)}<5")
    bf = hits_allowed = hr_allowed = bb_allowed = 0.0
    for row in starts:
        s = row["stat"]
        faced = _number(s.get("battersFaced", 0), "battersFaced")
        if faced <= 0:
            continue
        bf += faced
        hits_allowed += _number(s.get("hits", 0), "hits")
        hr_allowed += _number(s.get("homeRuns", 0), "homeRuns")
        bb_allowed += _number(s.get("baseOnBalls", 0), "baseOnBalls")
    if bf <= 0:
        raise MLBJointFeatureError("opposing pitcher BF history unavailable")
    park_site, park_factor = park_factor_for_venue(venue_id)

    batter_pa = sum(r["plate_appearances"] for r in pool)
    avg_pa = fmean(r["plate_appearances"] for r in pool)
    batter_hit_rate = sum(r["hits"] for r in pool) / batter_pa
    batter_hr_rate = sum(r["home_runs"] for r in pool) / batter_pa
    batter_bb_rate = sum(r["walks"] for r in pool) / batter_pa
    pitcher_hit = hits_allowed / bf
    pitcher_hr = hr_allowed / bf
    pitcher_bb = bb_allowed / bf
    baseline_tb = fmean(r["total_bases"] for r in pool)
    targets = {
        "hits": avg_pa * sqrt(max(0.0, batter_hit_rate * pitcher_hit)),
        "home_runs": avg_pa * sqrt(max(0.0, batter_hr_rate * pitcher_hr)),
        "walks": avg_pa * sqrt(max(0.0, batter_bb_rate * pitcher_bb)),
        "total_bases": baseline_tb * float(park_factor),
    }
    weights = [1.0 / len(pool)] * len(pool)
    for _ in range(3):
        for field in ("hits", "home_runs", "walks", "total_bases"):
            weights = _tilt(weights, pool, field, targets[field])

    context = {
        "opposing_pitcher_id": int(opposing_pitcher_id),
        "pitcher_starts": len(starts),
        "park_site": park_site,
        "park_factor": float(park_factor),
        "target_means": targets,
        "whole_row_reweighting": True,
    }
    identity = {
        "feature_version": FEATURE_VERSION,
        "batter_id": int(batter_id),
        "target_date": target_date.isoformat(),
        "history_pool": pool,
        "history_weights": weights,
        "prior_pool": prior_pool or None,
        "context": context,
    }
    out = {
        "history_pool": pool,
        "history_weights": weights,
        "matchup": context,
        "feature_version": FEATURE_VERSION,
        "feature_source_hash": _sha(identity),
    }
    if prior_pool:
        out["prior_pool"] = prior_pool
    return out


def build_pitcher_joint_features(
    source: MLBGenericHistorySource,
    *,
    pitcher_id: int,
    target_date: date,
    window: int = 10,
) -> dict[str, Any]:
    pitching = source.player_rows(
        player_id=pitcher_id, group="pitching", target_date=target_date
    )
    starts = [
        r for r in pitching
        if _number(r["stat"].get("gamesStarted", 0), "gamesStarted") >= 1
    ]
    recent = starts[-window:]
    older = starts[-(window + 20):-window]
    if len(recent) < 5:
        raise MLBJointFeatureError(f"pitcher history insufficient {len(recent)}<5")
    pool = _pitcher_pool(recent)
    prior_pool = _pitcher_pool(older)
    if len(prior_pool) < 5:
        prior_pool = []

    identity = {
        "feature_version": FEATURE_VERSION,
        "pitcher_id": int(pitcher_id),
        "target_date": target_date.isoformat(),
        "history_pool": pool,
        "prior_pool": prior_pool or None,
    }
    out = {
        "history_pool": pool,
        "feature_version": FEATURE_VERSION,
        "feature_source_hash": _sha(identity),
    }
    if prior_pool:
        out["prior_pool"] = prior_pool
    return out
