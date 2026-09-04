from __future__ import annotations

"""CFB line-movement recap handling for SportsEdge.

This module preserves market-movement information from public recap sources such
as Todd Fuhrman while preventing post-game outcome fields from leaking into
pregame Model_P or Truth-Gate decisions.
"""

from dataclasses import dataclass, asdict
from typing import Any, Mapping

SOURCE_ROLE = "CONTEXT_ONLY"
MODEL_P_ELIGIBLE = False
TRUTH_GATE_ELIGIBLE = False

LIVE_ALLOWED_FIELDS = (
    "game",
    "side_open",
    "side_current_or_close",
    "side_move_points",
    "total_open",
    "total_current_or_close",
    "total_move_points",
)

POSTGAME_ONLY_FIELDS = (
    "final_score",
    "ats_winner",
    "ou_result",
    "move_side_won",
)


class CFBLineMovementContextError(ValueError):
    pass


@dataclass(frozen=True)
class CFBLineMovementObservation:
    source: str
    source_role: str
    model_p_eligible: bool
    truth_gate_eligible: bool
    game: str
    side_open: float | None
    side_current_or_close: float | None
    side_move_points: float | None
    total_open: float | None
    total_current_or_close: float | None
    total_move_points: float | None
    postgame_only: dict[str, Any]
    prohibited_uses: tuple[str, ...]


def _num(value: Any, field: str) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise CFBLineMovementContextError(f"{field} must be numeric")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise CFBLineMovementContextError(f"{field} must be numeric") from exc


def normalize_cfb_line_movement(
    row: Mapping[str, Any],
    *,
    source: str = "@ToddFuhrman",
) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise CFBLineMovementContextError("row must be a mapping")

    game = str(row.get("game") or "").strip()
    if not game:
        raise CFBLineMovementContextError("game is required")

    side_open = _num(row.get("side_open"), "side_open")
    side_close = _num(row.get("side_current_or_close"), "side_current_or_close")
    side_move = _num(row.get("side_move_points"), "side_move_points")
    total_open = _num(row.get("total_open"), "total_open")
    total_close = _num(row.get("total_current_or_close"), "total_current_or_close")
    total_move = _num(row.get("total_move_points"), "total_move_points")

    # Compute movement if a source omitted the explicit move column.
    if side_move is None and side_open is not None and side_close is not None:
        side_move = side_close - side_open
    if total_move is None and total_open is not None and total_close is not None:
        total_move = total_close - total_open

    postgame_only = {
        key: row.get(key)
        for key in POSTGAME_ONLY_FIELDS
        if key in row
    }

    observation = CFBLineMovementObservation(
        source=str(source),
        source_role=SOURCE_ROLE,
        model_p_eligible=MODEL_P_ELIGIBLE,
        truth_gate_eligible=TRUTH_GATE_ELIGIBLE,
        game=game,
        side_open=side_open,
        side_current_or_close=side_close,
        side_move_points=side_move,
        total_open=total_open,
        total_current_or_close=total_close,
        total_move_points=total_move,
        postgame_only=postgame_only,
        prohibited_uses=(
            "model_p_vote",
            "confidence_boost_from_agreement",
            "truth_gate_promotion_evidence",
            "postgame_outcome_leakage_into_pregame",
            "move_side_won_as_predictive_feature_without_backtest",
        ),
    )
    return asdict(observation)


def pregame_view(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Return only fields safe for a pregame RUN IT context layer."""
    return {
        "source": observation.get("source"),
        "source_role": SOURCE_ROLE,
        "model_p_eligible": False,
        "truth_gate_eligible": False,
        **{field: observation.get(field) for field in LIVE_ALLOWED_FIELDS},
    }
