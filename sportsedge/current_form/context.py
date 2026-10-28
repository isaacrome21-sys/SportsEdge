"""Assemble the labeled `current_form_context` block for a card row.

This is the ONLY integration surface of this package. The card builder
may attach the returned block to a game's info pack; the block is
self-labeling ("RESEARCH_CONTEXT_ONLY") and carries its receipts so a
reader can audit exactly which public data informed the research view.

`suggested_adjustments` are ADVISORY research annotations computed by
the declared formulas in the factoring spec
(research/analytics_current_form_20261027/CURRENT_FORM_FACTORING_SPEC_20261027.md)
and hard-capped there. They are displayed next to a LEAN, never folded
into a model probability, a price, an EV figure, a verified status, or
PLAY eligibility by this package. Enforcement of the caps lives here
(one place) so a caller cannot exceed them through this surface.

Fail-closed per signal: a missing source yields an entry with
status MISSING and no values; the block itself still returns.
"""
from __future__ import annotations

from typing import Any

LABEL = "RESEARCH_CONTEXT_ONLY"

# Factoring-spec caps (points on a spread/total scale, probability on a
# 0-1 scale). Changing these numbers is a spec change, not a code tweak:
# it requires amending the factoring spec document in the same PR.
CAPS = {
    "max_single_signal_points": 0.5,
    "max_total_points": 1.0,
    "max_probability_shift": 0.02,
}


def capped_adjustment(kind: str, raw_value: float, *, signal: str, source: str) -> dict[str, Any]:
    """Clamp one suggested adjustment to its spec cap, visibly."""
    cap = CAPS["max_single_signal_points"] if kind == "points" else CAPS["max_probability_shift"]
    applied = max(-cap, min(cap, raw_value))
    return {
        "signal": signal,
        "source": source,
        "kind": kind,
        "raw_value": round(raw_value, 4),
        "applied_value": round(applied, 4),
        "capped": applied != raw_value,
        "label": LABEL,
    }


def cap_total(adjustments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enforce the total-points cap across point adjustments, in order."""
    remaining = CAPS["max_total_points"]
    out: list[dict[str, Any]] = []
    for adjustment in adjustments:
        if adjustment["kind"] != "points":
            out.append(adjustment)
            continue
        value = adjustment["applied_value"]
        clamped = max(-remaining, min(remaining, value))
        remaining -= abs(clamped)
        out.append({**adjustment, "applied_value": round(clamped, 4),
                    "capped": adjustment["capped"] or clamped != value})
    return out


def build_context_block(signals: list[dict[str, Any]], adjustments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Wrap fetcher outputs + capped suggestions into the card block.

    `signals` are fetcher result dicts (OK or MISSING). Their raw row
    payloads (players/teams) are passed through under `data`; receipts
    are hoisted into `receipts` so provenance reads in one place.
    """
    entries: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    for signal in signals:
        entry = {key: value for key, value in signal.items() if key not in ("receipt", "receipts", "body")}
        entry["label"] = LABEL
        entries.append(entry)
        if "receipt" in signal:
            receipts.append(signal["receipt"])
        receipts.extend(signal.get("receipts", []))
    return {
        "current_form_context": {
            "label": LABEL,
            "signals": entries,
            "suggested_adjustments": cap_total(adjustments or []),
            "receipts": receipts,
            "notice": (
                "Public current-form analytics shown as labeled research "
                "context. Not a model input; does not change any price, "
                "probability, verified status, or PLAY eligibility."
            ),
        }
    }
