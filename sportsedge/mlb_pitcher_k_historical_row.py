"""PIT-safe historical row adapter for the MLB pitcher-K candidate test.

Historical reconstruction is intentionally distinct from live-main Statcast
provenance. These rows may be used only for the frozen 2023/2024 development
split and candidate-specific 2025 test. They are never forward evidence.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from math import isfinite
from typing import Any, Mapping, Sequence

from .mlb_pitcher_k_composite_candidate import (
    AUTHORITY,
    SCHEMA as COMPOSITE_SCHEMA,
)
from .mlb_pitcher_k_probability_candidate import HALF_LINES
from .pitcher_joint_engine import price_pitcher_market
from .statcast_daily_source import SOURCE as STATCAST_SOURCE, fetch_daily_statcast

OUTPUT_SCHEMA = "MLB_PITCHER_K_SKILL_BOUND_CANDIDATE_V1"
PROVENANCE_SCHEMA = "MLB_PITCHER_K_HISTORICAL_STATCAST_PROVENANCE_V1"
EVALUATION_USE = "CANDIDATE_SPECIFIC_HISTORICAL_TEST_ONLY"


class PitcherKHistoricalRowError(ValueError):
    pass


def _rate(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise PitcherKHistoricalRowError(f"{name} must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise PitcherKHistoricalRowError(f"{name} must be numeric") from exc
    if not isfinite(out) or not 0.0 <= out <= 1.0:
        raise PitcherKHistoricalRowError(f"{name} outside [0,1]")
    return out


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise PitcherKHistoricalRowError(f"{name} must be integer")
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise PitcherKHistoricalRowError(f"{name} must be integer") from exc
    if out <= 0:
        raise PitcherKHistoricalRowError(f"{name} must be positive")
    return out


def _historical_receipt(
    *,
    target_date: date,
    window_start: str,
    window_end: str,
    retrieved_at: str,
    raw_pitch_rows: int,
) -> dict[str, Any]:
    if window_end != target_date.isoformat():
        raise PitcherKHistoricalRowError(
            "Statcast historical query end must equal target date exclusive"
        )
    try:
        start = date.fromisoformat(window_start)
    except ValueError as exc:
        raise PitcherKHistoricalRowError("historical Statcast window_start invalid") from exc
    if start >= target_date:
        raise PitcherKHistoricalRowError("historical Statcast window must precede target date")
    if int(raw_pitch_rows) <= 0:
        raise PitcherKHistoricalRowError("historical Statcast snapshot must contain pitch rows")
    if not str(retrieved_at or "").strip():
        raise PitcherKHistoricalRowError("historical Statcast retrieval identity required")
    return {
        "schema": PROVENANCE_SCHEMA,
        "source": STATCAST_SOURCE,
        "mode": "HISTORICAL_RECONSTRUCTION",
        "target_date": target_date.isoformat(),
        "window_start": window_start,
        "query_end_exclusive": window_end,
        "retrieved_at": str(retrieved_at),
        "raw_pitch_rows": int(raw_pitch_rows),
        "same_day_rows_included": False,
        "future_rows_included": False,
        "historical_reconstruction": True,
        "backfill": True,
        "forward_evidence_eligible": False,
        "promotion_authority": False,
        "evaluation_use": EVALUATION_USE,
    }


def acquire_historical_statcast_pitcher(
    *,
    pitcher_id: int,
    target_date: date,
    opener,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Acquire the frozen rolling Statcast context with target date as exclusive end."""
    snapshot = fetch_daily_statcast(
        end_date=target_date,
        days=30,
        opener=opener,
    )
    row = next(
        (r for r in snapshot.pitcher_rows if str(r.get("entity_id")) == str(int(pitcher_id))),
        None,
    )
    if not isinstance(row, Mapping):
        raise PitcherKHistoricalRowError("pitcher missing from historical Statcast snapshot")
    context = {
        "entity_id": str(int(pitcher_id)),
        "swings": row.get("swings"),
        "whiffs": row.get("whiffs"),
        "whiff_rate": row.get("whiff_rate"),
        "out_of_zone_pitches": row.get("out_of_zone_pitches"),
        "chases": row.get("chases"),
        "chase_rate": row.get("chase_rate"),
        "pitcher_hand": row.get("pitcher_hand"),
        "window_start": snapshot.start_date,
        "window_end": snapshot.end_date,
    }
    receipt = _historical_receipt(
        target_date=target_date,
        window_start=snapshot.start_date,
        window_end=snapshot.end_date,
        retrieved_at=snapshot.retrieved_at,
        raw_pitch_rows=snapshot.raw_pitch_rows,
    )
    return context, receipt


def bind_historical_statcast_skill(
    candidate: Mapping[str, Any],
    *,
    pitcher_context: Mapping[str, Any],
    provenance: Mapping[str, Any],
    target_date: date,
) -> dict[str, Any]:
    if not isinstance(candidate, Mapping) or candidate.get("schema") != COMPOSITE_SCHEMA:
        raise PitcherKHistoricalRowError("unexpected composite candidate")
    if candidate.get("authority") != AUTHORITY:
        raise PitcherKHistoricalRowError("candidate authority must remain research only")
    if candidate.get("deployment") is not False or candidate.get("model_p_eligible") is not False:
        raise PitcherKHistoricalRowError("candidate cannot already be deployed/model eligible")
    if not isinstance(provenance, Mapping) or provenance.get("schema") != PROVENANCE_SCHEMA:
        raise PitcherKHistoricalRowError("historical Statcast provenance receipt required")
    if provenance.get("mode") != "HISTORICAL_RECONSTRUCTION":
        raise PitcherKHistoricalRowError("historical provenance mode invalid")
    if provenance.get("target_date") != target_date.isoformat():
        raise PitcherKHistoricalRowError("historical provenance target date mismatch")
    if provenance.get("query_end_exclusive") != target_date.isoformat():
        raise PitcherKHistoricalRowError("historical provenance is not target-date exclusive")
    if provenance.get("forward_evidence_eligible") is not False:
        raise PitcherKHistoricalRowError("historical reconstruction cannot be forward evidence")
    if provenance.get("promotion_authority") is not False:
        raise PitcherKHistoricalRowError("historical reconstruction cannot grant promotion authority")
    if provenance.get("backfill") is not True or provenance.get("historical_reconstruction") is not True:
        raise PitcherKHistoricalRowError("historical reconstruction flags required")
    if provenance.get("same_day_rows_included") is not False or provenance.get("future_rows_included") is not False:
        raise PitcherKHistoricalRowError("same-day/future Statcast rows forbidden")

    whiff_rate = _rate(pitcher_context.get("whiff_rate"), "whiff_rate")
    chase_rate = _rate(pitcher_context.get("chase_rate"), "chase_rate")
    swings = _positive_int(pitcher_context.get("swings"), "swings")
    whiffs = _positive_int(pitcher_context.get("whiffs"), "whiffs")
    out_zone = _positive_int(pitcher_context.get("out_of_zone_pitches"), "out_of_zone_pitches")
    chases = _positive_int(pitcher_context.get("chases"), "chases")
    if whiffs > swings or chases > out_zone:
        raise PitcherKHistoricalRowError("historical Statcast counts impossible")
    if abs(whiff_rate - whiffs / swings) > 1e-6:
        raise PitcherKHistoricalRowError("whiff_rate does not match counts")
    if abs(chase_rate - chases / out_zone) > 1e-6:
        raise PitcherKHistoricalRowError("chase_rate does not match counts")
    hand = str(pitcher_context.get("pitcher_hand") or "").upper()
    if hand not in {"L", "R"}:
        raise PitcherKHistoricalRowError("pitcher_hand must be L or R")
    if pitcher_context.get("window_end") != target_date.isoformat():
        raise PitcherKHistoricalRowError("pitcher context window is not target-date exclusive")

    out = deepcopy(dict(candidate))
    out["schema"] = OUTPUT_SCHEMA
    out["components"] = deepcopy(dict(candidate.get("components") or {}))
    out["components"]["pitcher_skill"] = {
        "source": "BASEBALL_SAVANT_STATCAST_30D",
        "whiff_rate": whiff_rate,
        "chase_rate": chase_rate,
        "swings": swings,
        "whiffs": whiffs,
        "out_of_zone_pitches": out_zone,
        "chases": chases,
        "pitcher_hand": hand,
        "window_start": str(pitcher_context.get("window_start")),
        "window_end": str(pitcher_context.get("window_end")),
        "provenance": deepcopy(dict(provenance)),
    }
    out["missing_components"] = []
    out["source_complete"] = True
    out["evaluation_ready"] = True
    out["evaluation_use"] = EVALUATION_USE
    out["historical_reconstruction"] = True
    out["forward_evidence_eligible"] = False
    out["deployment"] = False
    out["model_p_eligible"] = False
    out["probability_formula"] = None
    out["fit_parameters"] = None
    return out


def incumbent_p_over(
    *,
    candidate: Mapping[str, Any],
    history_pool: Sequence[Mapping[str, Any]],
    game_id: int,
    pitcher_id: int,
) -> dict[str, float]:
    if not isinstance(candidate, Mapping) or candidate.get("schema") != OUTPUT_SCHEMA:
        raise PitcherKHistoricalRowError("skill-bound candidate required")
    if not 5 <= len(history_pool) <= 10:
        raise PitcherKHistoricalRowError("incumbent history must contain 5..10 prior starts")
    components = candidate.get("components") or {}
    opponent = components.get("opponent_k")
    if not isinstance(opponent, Mapping):
        raise PitcherKHistoricalRowError("opponent-K component required")
    adjustment = deepcopy(dict(opponent))
    lineup = components.get("lineup_k")
    if lineup is not None:
        if not isinstance(lineup, Mapping):
            raise PitcherKHistoricalRowError("lineup-K component invalid")
        adjustment["lineup_k_adjustment"] = deepcopy(dict(lineup))

    out: dict[str, float] = {}
    for line in HALF_LINES:
        priced = price_pitcher_market(
            {
                "game_id": int(game_id),
                "market": "PITCHER_K",
                "entity_id": str(int(pitcher_id)),
                "line": float(line),
                "side": "OVER",
                "features": {
                    "history_pool": list(history_pool),
                    "opp_k_adjustment": adjustment,
                },
            }
        )
        out[f"{float(line):.1f}"] = float(priced["model_p"])
    return out


def build_historical_evaluation_row(
    *,
    season: int,
    target_date: date,
    game_id: int,
    pitcher_id: int,
    candidate: Mapping[str, Any],
    history_pool: Sequence[Mapping[str, Any]],
    realized_strikeouts: int,
    realized_batters_faced: int,
) -> dict[str, Any]:
    if int(season) != target_date.year or int(season) not in {2023, 2024, 2025}:
        raise PitcherKHistoricalRowError("row season outside frozen 2023-2025 split")
    if candidate.get("historical_reconstruction") is not True:
        raise PitcherKHistoricalRowError("historical candidate required")
    if candidate.get("forward_evidence_eligible") is not False:
        raise PitcherKHistoricalRowError("historical row cannot be forward evidence")
    k = int(realized_strikeouts)
    bf = int(realized_batters_faced)
    if bf <= 0 or k < 0 or k > bf:
        raise PitcherKHistoricalRowError("realized K/BF impossible")
    return {
        "schema": "MLB_PITCHER_K_HISTORICAL_EVALUATION_ROW_V1",
        "season": int(season),
        "target_date": target_date.isoformat(),
        "game_id": int(game_id),
        "pitcher_id": str(int(pitcher_id)),
        "candidate": deepcopy(dict(candidate)),
        "realized_strikeouts": k,
        "realized_batters_faced": bf,
        "incumbent_p_over": incumbent_p_over(
            candidate=candidate,
            history_pool=history_pool,
            game_id=game_id,
            pitcher_id=pitcher_id,
        ),
        "historical_reconstruction": True,
        "backfill": True,
        "forward_evidence_eligible": False,
        "promotion_authority": False,
        "evaluation_use": EVALUATION_USE,
    }
