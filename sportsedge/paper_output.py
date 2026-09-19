from __future__ import annotations

from typing import Any, Mapping


PAPER_LABEL = "PAPER_NOT_OFFICIAL"
FORBIDDEN_OFFICIAL_LABELS = frozenset({"OFFICIAL", "LIVE_PROMOTED", "STAKEABLE"})


def paper_candidate(*, sport: str, market: str, selection: str, note: str = "") -> dict[str, Any]:
    """Build a visible non-official candidate envelope."""
    return {
        "schema": "SPORTSEDGE_PAPER_CANDIDATE_V1",
        "output_class": "PAPER",
        "label": PAPER_LABEL,
        "sport": sport,
        "market": market,
        "selection": selection,
        "note": note,
        "official_authority": False,
        "promotion_authority": False,
        "staking_authority": False,
        "eligibility_changed": False,
    }


def assert_not_official(payload: Mapping[str, Any]) -> None:
    if payload.get("official_authority") is True:
        raise ValueError("PAPER_OUTPUT_CANNOT_SET_OFFICIAL_AUTHORITY")
    if payload.get("output_class") in FORBIDDEN_OFFICIAL_LABELS:
        raise ValueError("PAPER_OUTPUT_USED_FORBIDDEN_OFFICIAL_LABEL")
    if payload.get("label") in FORBIDDEN_OFFICIAL_LABELS:
        raise ValueError("PAPER_OUTPUT_USED_FORBIDDEN_OFFICIAL_LABEL")
