"""Fail-closed adapter for timestamped, game-identified MLB inning results.

Consumes a local JSON evidence export only. Does not download data, invent
fixtures, treat archive modification times as event times, or authorize PLAY.
"""
from __future__ import annotations

import json
from pathlib import Path

from sportsedge.mlb_period_counts_empirical import _instant
from sportsedge.mlb_period_walkforward import evaluate_period_walkforward


def load_historical_inning_export(path: str | Path) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != "MLB_HISTORICAL_INNING_EXPORT_V1":
        raise ValueError("UNRECOGNIZED_HISTORICAL_EXPORT")
    if not isinstance(payload.get("source_url"), str) or not payload["source_url"].startswith("https://"):
        raise ValueError("MISSING_SOURCE_URL")
    if not isinstance(payload.get("observed_at"), str):
        raise ValueError("MISSING_OBSERVATION_TIME")
    _instant(payload["observed_at"])
    if payload.get("availability_attestation_authenticity_verified") is True:
        raise ValueError("UNSUPPORTED_AUTHENTICITY_CLAIM")
    if payload.get("availability_attestation_authenticity_verified") is False:
        raise ValueError("UNVERIFIED_AVAILABILITY_ATTESTATION")
    games = payload.get("games")
    if not isinstance(games, list) or not games:
        raise ValueError("EMPTY_HISTORICAL_GAMES")
    seen = set()
    result = []
    for row in games:
        if not isinstance(row, dict):
            raise ValueError("INVALID_GAME_ROW")
        game_id = row.get("game_id")
        if not isinstance(game_id, (str, int)) or isinstance(game_id, bool) or not str(game_id):
            raise ValueError("INVALID_GAME_ID")
        if str(game_id) in seen:
            raise ValueError("DUPLICATE_GAME_ID")
        seen.add(str(game_id))
        start = _instant(row.get("start_time"))
        if start > _instant(payload["observed_at"]):
            raise ValueError("GAME_AFTER_OBSERVATION")
        if "result_available_at" not in row:
            raise ValueError("MISSING_RESULT_AVAILABILITY")
        available = _instant(row["result_available_at"])
        if available <= start or available > _instant(payload["observed_at"]):
            raise ValueError("INVALID_RESULT_AVAILABILITY")
        innings = row.get("inning_runs")
        if (not isinstance(innings, list) or len(innings) < 9
                or any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in innings)):
            raise ValueError("INCOMPLETE_OR_INVALID_INNINGS")
        result.append({"game_id": str(game_id), "start_time": row["start_time"],
                       "result_available_at": row["result_available_at"],
                       "inning_runs": innings})
    return result


def evaluate_historical_export(path: str | Path, *, innings: int,
                               min_train: int = 20, half_line: float = 1.5) -> dict:
    games = load_historical_inning_export(path)
    report = evaluate_period_walkforward(
        games, innings=innings, min_train=min_train, half_line=half_line)
    report["source_kind"] = "LOCAL_HISTORICAL_EXPORT"
    report["research_only"] = True
    return report
