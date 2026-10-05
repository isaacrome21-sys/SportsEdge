"""Bridge NFL_SCORE_COUNTS_G1 forward artifacts into the existing game-market pricer.

The score-count candidate already emits an empirical joint final-score
distribution. This module converts that exact 50k-path distribution into the
grid contract used by the existing unified NFL game-market engine. Sportsbook
lines enter only after the model distribution exists.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping, Sequence

from sportsedge.sports.nfl.score_counts_artifact import PREDICTION_SCHEMA
from sportsedge.sports.nfl.unified_market_engine import price_game_market

SCHEMA = "SPORTSEDGE_NFL_SCORE_COUNTS_G1_MARKET_BRIDGE_V1"


class ScoreCountMarketBridgeError(ValueError):
    pass


def _int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ScoreCountMarketBridgeError(f"{field}:INTEGER_REQUIRED")
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise ScoreCountMarketBridgeError(f"{field}:INTEGER_REQUIRED") from exc
    if str(value).strip() not in {str(out), f"{out}.0"} and not isinstance(value, int):
        try:
            if float(value) != float(out):
                raise ScoreCountMarketBridgeError(f"{field}:INTEGER_REQUIRED")
        except (TypeError, ValueError) as exc:
            raise ScoreCountMarketBridgeError(f"{field}:INTEGER_REQUIRED") from exc
    return out


def _prediction_game(prediction: Mapping[str, Any], game_id: str) -> dict[str, Any]:
    if prediction.get("schema") != PREDICTION_SCHEMA:
        raise ScoreCountMarketBridgeError("SCORE_COUNT_PREDICTION_SCHEMA_INVALID")
    games = prediction.get("games")
    if not isinstance(games, Sequence) or isinstance(games, (str, bytes, bytearray)):
        raise ScoreCountMarketBridgeError("SCORE_COUNT_PREDICTION_GAMES_REQUIRED")
    matches = [dict(row) for row in games if isinstance(row, Mapping) and str(row.get("game_id")) == str(game_id)]
    if len(matches) != 1:
        raise ScoreCountMarketBridgeError(f"SCORE_COUNT_GAME_IDENTITY_REQUIRED:{game_id}:{len(matches)}")
    return matches[0]


def score_count_grid(game: Mapping[str, Any]) -> list[list[float]]:
    paths = _int(game.get("paths"), "paths")
    if paths != 50000:
        raise ScoreCountMarketBridgeError("SCORE_COUNT_PATHS_MUST_EQUAL_50000")
    rows = game.get("joint_score_distribution")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)) or not rows:
        raise ScoreCountMarketBridgeError("JOINT_SCORE_DISTRIBUTION_REQUIRED")

    parsed: list[tuple[int, int, int]] = []
    total = 0
    max_home = max_away = 0
    seen: set[tuple[int, int]] = set()
    for idx, raw in enumerate(rows):
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)) or len(raw) != 3:
            raise ScoreCountMarketBridgeError(f"JOINT_SCORE_ROW_INVALID:{idx}")
        home = _int(raw[0], f"row[{idx}].home_score")
        away = _int(raw[1], f"row[{idx}].away_score")
        count = _int(raw[2], f"row[{idx}].count")
        if home < 0 or away < 0 or count <= 0:
            raise ScoreCountMarketBridgeError(f"JOINT_SCORE_ROW_OUT_OF_RANGE:{idx}")
        key = (home, away)
        if key in seen:
            raise ScoreCountMarketBridgeError(f"JOINT_SCORE_DUPLICATE:{home}:{away}")
        seen.add(key)
        parsed.append((home, away, count))
        total += count
        max_home = max(max_home, home)
        max_away = max(max_away, away)

    if total != paths:
        raise ScoreCountMarketBridgeError(f"JOINT_SCORE_PATH_MASS_MISMATCH:{total}:{paths}")

    grid = [[0.0 for _ in range(max_away + 1)] for _ in range(max_home + 1)]
    for home, away, count in parsed:
        grid[home][away] = count / paths
    mass = sum(sum(row) for row in grid)
    if not isfinite(mass) or abs(mass - 1.0) > 1e-12:
        raise ScoreCountMarketBridgeError(f"JOINT_SCORE_PROBABILITY_MASS_INVALID:{mass}")
    return grid


def score_count_paths(game: Mapping[str, Any]) -> list[dict[str, int]]:
    """Expand the exact empirical distribution back to its 50k score paths.

    Ordering is canonical by home score then away score. Stored integer counts
    are expanded directly; no probability round-trip can alter path mass.
    """
    # Reuse the full validator first.
    score_count_grid(game)
    raw_rows = game["joint_score_distribution"]
    parsed = sorted(
        (
            _int(raw[0], "home_score"),
            _int(raw[1], "away_score"),
            _int(raw[2], "count"),
        )
        for raw in raw_rows
    )
    out: list[dict[str, int]] = []
    simulation_id = 0
    for home, away, count in parsed:
        for _ in range(count):
            out.append({
                "simulation_id": simulation_id,
                "home_score": home,
                "away_score": away,
            })
            simulation_id += 1
    if len(out) != 50000:
        raise ScoreCountMarketBridgeError(f"EXPANDED_SCORE_PATH_COUNT_INVALID:{len(out)}")
    return out


def price_score_count_game_markets(
    prediction: Mapping[str, Any],
    *,
    game_id: str,
    requests: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    game = _prediction_game(prediction, game_id)
    grid = score_count_grid(game)
    rows: list[dict[str, Any]] = []
    for request in requests:
        try:
            rows.append(price_game_market(grid, request))
        except (ValueError, TypeError, KeyError) as exc:
            rows.append({
                "market": request.get("market") if isinstance(request, Mapping) else None,
                "selection": request.get("selection") if isinstance(request, Mapping) else None,
                "team": request.get("team") if isinstance(request, Mapping) else None,
                "line": request.get("line") if isinstance(request, Mapping) else None,
                "status": "NO_MODEL",
                "reason": str(exc),
            })
    return {
        "schema": SCHEMA,
        "candidate_family": "NFL_SCORE_COUNTS_G1",
        "game_id": str(game_id),
        "fit_artifact_sha256": prediction.get("fit_artifact_sha256"),
        "prediction_sha256": prediction.get("prediction_sha256"),
        "joint_score_distribution_sha256": game.get("joint_score_distribution_sha256"),
        "paths": 50000,
        "game_markets": rows,
        "market_data_used_to_create_distribution": False,
        "authority": {
            "research_only": True,
            "creates_model_p": False,
            "pricing": True,
            "truth_gate": False,
            "promotion": False,
            "staking": False,
            "official": False,
        },
    }


__all__ = [
    "SCHEMA",
    "ScoreCountMarketBridgeError",
    "price_score_count_game_markets",
    "score_count_grid",
    "score_count_paths",
]
