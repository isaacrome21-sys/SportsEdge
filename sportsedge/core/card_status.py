"""Card row status contract shared by all SportsEdge sports.

TRIAL is a paper-only evidence state. It requires a real Model_P, a real market
edge, and no hard blocker, but it does not require promotion or a frozen edge
floor. PASS and OFFICIAL remain promotion-gated. Confidence, stake, and units
exist only on OFFICIAL rows. Context leans never change status.
"""
from __future__ import annotations

OFFICIAL = "OFFICIAL"
TRIAL = "TRIAL"
PASS = "PASS"
BLOCKED = "BLOCKED"
NO_ENGINE = "NO_ENGINE"

_NON_OFFICIAL_WAGER_FIELDS = ("confidence", "stake", "units", "bet_size")


def _row(status: str, reasons: list[str]) -> dict:
    return {
        "status": status,
        "reasons": list(dict.fromkeys(reasons)),
        "confidence_allowed": status == OFFICIAL,
        "stake_allowed": status == OFFICIAL,
        "paper_only": status == TRIAL,
    }


def resolve_row_status(
    *,
    engine_exists: bool,
    model_p,
    blockers,
    promoted: bool,
    edge=None,
    edge_floor=None,
    trial_min_edge: float = 0.0,
) -> dict:
    """Resolve the governance label for one model/market row.

    TRIAL never changes promotion state. It only exposes a priced, positive-edge
    row for paper tracking so CLV/closing-line evidence can accumulate.
    """
    reasons = list(dict.fromkeys(blockers or []))
    hard_reasons = [reason for reason in reasons if reason != "NOT_PROMOTED"]

    if not engine_exists:
        return _row(NO_ENGINE, ["NO_ENGINE"])

    if model_p is None:
        if not hard_reasons:
            raise ValueError("MISSING_MODEL_P_WITHOUT_REASON")
        if not promoted:
            hard_reasons.append("NOT_PROMOTED")
        return _row(BLOCKED, hard_reasons)

    model_p = float(model_p)
    if not 0.0 < model_p < 1.0:
        raise ValueError("MODEL_P_OUT_OF_RANGE")

    # Hard blockers always win, regardless of promotion or paper-trial status.
    if hard_reasons:
        if not promoted:
            hard_reasons.append("NOT_PROMOTED")
        return _row(BLOCKED, hard_reasons)

    if edge is None:
        return _row(
            BLOCKED,
            ["MARKET_EDGE_MISSING"] + ([] if promoted else ["NOT_PROMOTED"]),
        )
    edge = float(edge)

    # Unpromoted markets can be surfaced only as paper TRIAL rows.
    if not promoted:
        if edge > float(trial_min_edge):
            return _row(TRIAL, ["PAPER_ONLY", "NOT_PROMOTED"])
        return _row(BLOCKED, ["NOT_PROMOTED", "NO_POSITIVE_MODEL_EDGE"])

    # Promotion alone is insufficient for PASS/OFFICIAL; the floor must be frozen.
    if edge_floor is None:
        return _row(BLOCKED, ["NO_FROZEN_EDGE_FLOOR"])

    edge_floor = float(edge_floor)
    if edge < edge_floor:
        return _row(PASS, ["BELOW_EDGE_FLOOR"])
    return _row(OFFICIAL, [])


def assert_card_integrity(rows: list) -> None:
    """Raise on any rendered row that breaks the card-status contract."""
    for i, row in enumerate(rows):
        status = row.get("status")
        if status not in (OFFICIAL, TRIAL, PASS, BLOCKED, NO_ENGINE):
            raise ValueError(f"ROW_{i}_UNKNOWN_STATUS")

        if status != OFFICIAL:
            for field in _NON_OFFICIAL_WAGER_FIELDS:
                if row.get(field) not in (None, "", "—", 0, 0.0):
                    raise ValueError(f"ROW_{i}_{field.upper()}_ON_NON_OFFICIAL")

        if status in (TRIAL, PASS) and row.get("model_p") is None:
            raise ValueError(f"ROW_{i}_{status}_WITHOUT_MODEL_P")

        if status == TRIAL:
            if row.get("edge") is None:
                raise ValueError(f"ROW_{i}_TRIAL_WITHOUT_EDGE")
            if float(row["edge"]) <= 0.0:
                raise ValueError(f"ROW_{i}_TRIAL_WITHOUT_POSITIVE_EDGE")
            if row.get("paper_only") is False:
                raise ValueError(f"ROW_{i}_TRIAL_NOT_PAPER_ONLY")

        if status == BLOCKED and not row.get("reasons"):
            raise ValueError(f"ROW_{i}_BLOCKED_WITHOUT_REASON")
