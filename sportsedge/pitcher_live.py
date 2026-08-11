"""Fail-closed live candidate assembly for validated pitcher props."""
from __future__ import annotations

import json
from math import isfinite
from typing import Any, Mapping

from .bb_engine import FEATURE_CONTRACT_VERSION
from .identity_rng import build_hash, validate_build_hash
from .live_slate import LiveGame, LiveSlateError


SUPPORTED_PITCHER_MARKETS = {"PITCHER_BB"}


def _finite(name: str, value: Any, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(value, bool):
        raise LiveSlateError(f"{name} must be finite numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise LiveSlateError(f"{name} must be finite numeric") from exc
    if not isfinite(out) or (lo is not None and out < lo) or (hi is not None and out > hi):
        raise LiveSlateError(f"{name} out of range")
    return out


def _pool(name: str, value: Any) -> list[int]:
    if not isinstance(value, (list, tuple)) or not value:
        raise LiveSlateError(f"{name} must be a non-empty list/tuple")
    out = []
    for x in value:
        if isinstance(x, bool) or not isinstance(x, int) or x < 0:
            raise LiveSlateError(f"{name} must contain non-negative integers")
        out.append(x)
    return out


def _source_hash(feature_row: Mapping[str, Any]) -> str:
    raw = feature_row.get("source_subset_hash")
    if raw is None:
        if feature_row.get("provenance") is not None:
            raise LiveSlateError("provenance requires source_subset_hash")
        return "NO_PROVENANCE_HASH"
    try:
        return validate_build_hash(raw)
    except Exception as exc:
        raise LiveSlateError("invalid source_subset_hash") from exc


def _probable_pitcher_team(game: LiveGame, pitcher_id: int) -> int:
    away = pitcher_id == game.away_probable_pitcher_id
    home = pitcher_id == game.home_probable_pitcher_id
    if away and home:
        raise LiveSlateError("pitcher appears as both probable starters")
    if away:
        return game.away_team_id
    if home:
        return game.home_team_id
    raise LiveSlateError("pitcher is not the current MLB probable starter")


def assemble_pitcher_bb_candidate(*, game: LiveGame, feature_row: Mapping[str, Any], quote: Mapping[str, Any]) -> dict[str, Any]:
    if feature_row.get("market") != "PITCHER_BB":
        raise LiveSlateError("feature market does not match PITCHER_BB")
    if feature_row.get("feature_version") != FEATURE_CONTRACT_VERSION:
        raise LiveSlateError("pitcher BB feature contract mismatch")
    if feature_row.get("game_pk") != game.game_pk:
        raise LiveSlateError("feature game_pk does not match live game")
    pitcher_id = feature_row.get("player_id")
    if isinstance(pitcher_id, bool) or not isinstance(pitcher_id, int) or pitcher_id <= 0:
        raise LiveSlateError("feature player_id invalid")
    team_id = _probable_pitcher_team(game, pitcher_id)
    if feature_row.get("team_id") != team_id:
        raise LiveSlateError("feature team_id does not match probable-pitcher team")

    common = {"game_pk","player_id","team_id","market","feature_version","source_subset_hash","provenance"}
    expected = {"own_bb","own_bfp","rolling_league_rate","pool","league_pool"}
    extra = set(feature_row) - common - expected
    missing = expected - set(feature_row)
    if extra:
        raise LiveSlateError(f"unexpected PITCHER_BB feature fields: {sorted(extra)}")
    if missing:
        raise LiveSlateError(f"missing PITCHER_BB feature fields: {sorted(missing)}")
    own_bb = _finite("own_bb", feature_row["own_bb"], 0)
    own_bfp = _finite("own_bfp", feature_row["own_bfp"], 1)
    if own_bb > own_bfp:
        raise LiveSlateError("own_bb cannot exceed own_bfp")
    features = {
        "own_bb": own_bb,
        "own_bfp": own_bfp,
        "rolling_league_rate": _finite("rolling_league_rate", feature_row["rolling_league_rate"], .001, .5),
        "pool": _pool("pool", feature_row["pool"]),
        "league_pool": _pool("league_pool", feature_row["league_pool"]),
    }

    if str(quote.get("game_id")) != str(game.game_pk) or quote.get("market") != "PITCHER_BB" or str(quote.get("entity_id")) != str(pitcher_id):
        raise LiveSlateError("quote identity does not match probable-pitcher identity")
    line = _finite("line", quote.get("line"), 0)
    side = quote.get("side")
    if side not in ("OVER", "UNDER"):
        raise LiveSlateError("quote side must be OVER or UNDER")

    source_hash = _source_hash(feature_row)
    feature_json = json.dumps(features, sort_keys=True, separators=(",", ":"))
    identity = build_hash([
        str(game.game_pk), "PITCHER_BB", str(pitcher_id), format(line, ".12g"), side,
        FEATURE_CONTRACT_VERSION, source_hash, feature_json,
    ])
    model_input = {
        "game_id": str(game.game_pk), "market": "PITCHER_BB", "entity_id": str(pitcher_id),
        "line": quote.get("line"), "side": side, "build_hash": identity,
        "feature_version": FEATURE_CONTRACT_VERSION, "feature_source_hash": source_hash,
        "features": features,
    }
    if feature_row.get("provenance") is not None:
        model_input["provenance"] = feature_row["provenance"]
    clean_quote = dict(quote)
    clean_quote["game_id"] = str(game.game_pk)
    clean_quote["entity_id"] = str(pitcher_id)
    return {"model_input": model_input, "quote": clean_quote}
