"""Shared point-in-time feature builder for coherent MLB joint prop engines.

No sportsbook data is accepted. All rows must be strictly prior to target_date.
The v1 hitter matchup adjustment blends batter and opposing-starter rates while
preserving the batter's hit-type composition; pitcher features retain whole prior
start rows so every pitcher market is a marginal of the same workload/outcome pool.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from math import sqrt
from statistics import fmean
from typing import Any, Mapping

from .mlb_generic_features import MLBGenericFeatureError, MLBGenericHistorySource, _number, _outs_from_ip

FEATURE_VERSION = "mlb_joint_features_v1"

class MLBJointFeatureError(ValueError):
    pass


def _sha(v: Any) -> str:
    raw = json.dumps(v, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def _rate(num: float, den: float, name: str) -> float:
    if den <= 0:
        raise MLBJointFeatureError(f"{name}: denominator must be > 0")
    return max(0.0, min(1.0, num / den))


def _blend(a: float, b: float) -> float:
    # Symmetric, bounded, price-independent v1 matchup blend. This is a candidate
    # parameterization and must earn promotion behaviorally.
    return max(0.0, min(1.0, sqrt(max(0.0, a) * max(0.0, b))))


def build_hitter_joint_features(
    source: MLBGenericHistorySource,
    *,
    batter_id: int,
    opposing_pitcher_id: int,
    target_date: date,
) -> dict[str, Any]:
    batting = source.player_rows(player_id=batter_id, group="hitting", target_date=target_date)[-30:]
    if len(batting) < 10:
        raise MLBJointFeatureError(f"batter history insufficient {len(batting)}<10")

    totals = {k: 0.0 for k in ("pa", "h", "d", "t", "hr", "bb", "runs", "rbi", "sb")}
    pa_values: list[float] = []
    for row in batting:
        s = row["stat"]
        pa = _number(s.get("plateAppearances"), "plateAppearances")
        if pa <= 0:
            continue
        hits = _number(s.get("hits", 0), "hits")
        doubles = _number(s.get("doubles", 0), "doubles")
        triples = _number(s.get("triples", 0), "triples")
        hr = _number(s.get("homeRuns", 0), "homeRuns")
        totals["pa"] += pa; totals["h"] += hits; totals["d"] += doubles; totals["t"] += triples; totals["hr"] += hr
        totals["bb"] += _number(s.get("baseOnBalls", 0), "baseOnBalls")
        totals["runs"] += _number(s.get("runs", 0), "runs")
        totals["rbi"] += _number(s.get("rbi", 0), "rbi")
        totals["sb"] += _number(s.get("stolenBases", 0), "stolenBases")
        pa_values.append(pa)
    if totals["pa"] <= 0 or len(pa_values) < 10:
        raise MLBJointFeatureError("usable batter PA history insufficient")

    singles = max(0.0, totals["h"] - totals["d"] - totals["t"] - totals["hr"])
    batter_hit = _rate(totals["h"], totals["pa"], "batter_hit")
    batter_hr = _rate(totals["hr"], totals["pa"], "batter_hr")
    batter_bb = _rate(totals["bb"], totals["pa"], "batter_bb")

    pitching = source.player_rows(player_id=opposing_pitcher_id, group="pitching", target_date=target_date)
    starts = [r for r in pitching if _number(r["stat"].get("gamesStarted", 0), "gamesStarted") >= 1][-10:]
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

    matchup_hit = _blend(batter_hit, _rate(hits_allowed, bf, "pitcher_hit_allowed"))
    matchup_hr = _blend(batter_hr, _rate(hr_allowed, bf, "pitcher_hr_allowed"))
    matchup_bb = _blend(batter_bb, _rate(bb_allowed, bf, "pitcher_bb_allowed"))

    nonhr_hits = max(0.0, totals["h"] - totals["hr"])
    if nonhr_hits > 0:
        s_share = singles / nonhr_hits; d_share = totals["d"] / nonhr_hits; t_share = totals["t"] / nonhr_hits
    else:
        s_share, d_share, t_share = 1.0, 0.0, 0.0
    matchup_nonhr = max(0.0, matchup_hit - matchup_hr)
    p_single = matchup_nonhr * s_share
    p_double = matchup_nonhr * d_share
    p_triple = matchup_nonhr * t_share

    features = {
        "projected_pa": float(fmean(pa_values[-30:])),
        "p_single": p_single,
        "p_double": p_double,
        "p_triple": p_triple,
        "p_hr": matchup_hr,
        "p_bb": matchup_bb,
        "p_run_per_pa": _rate(totals["runs"], totals["pa"], "run_per_pa"),
        "p_rbi_per_pa": _rate(totals["rbi"], totals["pa"], "rbi_per_pa"),
        "p_sb_per_pa": _rate(totals["sb"], totals["pa"], "sb_per_pa"),
    }
    if sum(features[k] for k in ("p_single", "p_double", "p_triple", "p_hr", "p_bb")) > 1.0:
        raise MLBJointFeatureError("matchup-adjusted PA event mass exceeds 1")
    identity = {
        "feature_version": FEATURE_VERSION,
        "batter_id": int(batter_id), "opposing_pitcher_id": int(opposing_pitcher_id),
        "target_date": target_date.isoformat(), "features": features,
        "batter_rows": len(batting), "pitcher_starts": len(starts),
    }
    return {**features, "feature_version": FEATURE_VERSION, "feature_source_hash": _sha(identity)}


def build_pitcher_joint_features(
    source: MLBGenericHistorySource,
    *,
    pitcher_id: int,
    target_date: date,
    window: int = 10,
) -> dict[str, Any]:
    pitching = source.player_rows(player_id=pitcher_id, group="pitching", target_date=target_date)
    starts = [r for r in pitching if _number(r["stat"].get("gamesStarted", 0), "gamesStarted") >= 1][-window:]
    if len(starts) < 5:
        raise MLBJointFeatureError(f"pitcher history insufficient {len(starts)}<5")
    pool: list[dict[str, int]] = []
    for row in starts:
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
    identity = {
        "feature_version": FEATURE_VERSION, "pitcher_id": int(pitcher_id),
        "target_date": target_date.isoformat(), "history_pool": pool,
    }
    return {"history_pool": pool, "feature_version": FEATURE_VERSION, "feature_source_hash": _sha(identity)}
