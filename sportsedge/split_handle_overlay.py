from __future__ import annotations

from typing import Any, Mapping

RLM_TICKET_FLOOR = 70.0
MONEY_TICKET_GAP = 15.0
MIN_POINT_MOVE = 0.5


def classify_split_overlay(row: Mapping[str, Any]) -> dict[str, Any]:
    tickets = _pct(row.get("ticket_pct"))
    money = _pct(row.get("money_pct"))
    move = _float(row.get("line_move_points"))
    public_side = str(row.get("public_side") or "").strip().lower()
    line_side = str(row.get("line_moved_toward") or "").strip().lower()
    tags: list[str] = []
    action = "NO_OVERLAY"
    if tickets is not None and tickets >= RLM_TICKET_FLOOR and move is not None and abs(move) >= MIN_POINT_MOVE:
        if public_side and line_side and public_side != line_side:
            tags.append("RLM_TICKETS_VS_LINE")
            action = "CONTEXT_LEAN_AGAINST_PUBLIC"
    if tickets is not None and money is not None and abs(money - tickets) >= MONEY_TICKET_GAP:
        tags.append("MONEY_TICKET_DIVERGENCE")
        if action == "NO_OVERLAY":
            action = "CONTEXT_LEAN_WITH_MONEY"
    return {
        "schema": "SPLIT_HANDLE_OVERLAY_V1",
        "action": action,
        "tags": tags,
        "model_p_authority": False,
        "official_authority": False,
        "truth_gate_input": False,
        "may_downgrade_paper": bool(tags),
        "may_block_paper": action == "CONTEXT_LEAN_AGAINST_PUBLIC",
        "may_rewrite_model_p": False,
    }


def _pct(value: object) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if 0.0 <= out <= 100.0:
        return out
    return None


def _float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
