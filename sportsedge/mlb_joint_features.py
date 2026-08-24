"""Shared point-in-time feature builder for coherent MLB joint prop engines.

No sportsbook data is accepted. Hitter features retain whole strictly-prior game
rows; pitcher features retain whole strictly-prior start rows. This preserves
cross-market arithmetic and support before any richer PA-level PBP model exists.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from .mlb_generic_features import MLBGenericHistorySource, _number, _outs_from_ip

FEATURE_VERSION = "mlb_joint_features_v3"

class MLBJointFeatureError(ValueError):
    pass


def _sha(v: Any) -> str:
    raw = json.dumps(v, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def build_hitter_joint_features(source: MLBGenericHistorySource, *, batter_id: int, target_date: date, window: int = 30) -> dict[str, Any]:
    batting = source.player_rows(player_id=batter_id, group="hitting", target_date=target_date)[-window:]
    pool: list[dict[str, int]] = []
    for row in batting:
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
        values = {
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
        }
        pool.append(values)
    if len(pool) < 10:
        raise MLBJointFeatureError(f"batter history insufficient {len(pool)}<10")
    identity = {"feature_version": FEATURE_VERSION, "batter_id": int(batter_id), "target_date": target_date.isoformat(), "history_pool": pool}
    return {"history_pool": pool, "feature_version": FEATURE_VERSION, "feature_source_hash": _sha(identity)}


def build_pitcher_joint_features(source: MLBGenericHistorySource, *, pitcher_id: int, target_date: date, window: int = 10) -> dict[str, Any]:
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
    identity = {"feature_version": FEATURE_VERSION, "pitcher_id": int(pitcher_id), "target_date": target_date.isoformat(), "history_pool": pool}
    return {"history_pool": pool, "feature_version": FEATURE_VERSION, "feature_source_hash": _sha(identity)}
