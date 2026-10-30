"""Fail-closed presentation partition for unvalidated game research surfaces.

Existing owner >=+40% claimed-EV quarantine. This code does not alter
model calculations, grading rows, frozen terms, or betting eligibility.
"""
from __future__ import annotations

import math

EXTREME_CLAIMED_EV_QUARANTINE = 0.40
GAME_SURFACES = (
    "edges", "independent_candidates", "independent_watchlist",
    "lane_b_watchlist",
)
EV_KEYS = ("ev_per_dollar", "raw_ev_per_dollar", "reported_ev_per_dollar")
P_KEYS = ("estimate_p", "model_probability")


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def game_claim_hold(row):
    """Return (hold reason, max finite EV) from visible and hidden claims."""
    invalid_ev = False
    invalid_p = False
    evs = []

    def inspect(source):
        nonlocal invalid_ev, invalid_p
        if source is None:
            return
        if not isinstance(source, dict):
            invalid_ev = True
            return
        for key in EV_KEYS:
            if key in source and source[key] is not None:
                ev = _number(source[key])
                if ev is None:
                    invalid_ev = True
                else:
                    evs.append(ev)
        for key in P_KEYS:
            if key in source and source[key] is not None:
                p = _number(source[key])
                if p is None or not 0 <= p <= 1:
                    invalid_p = True

    inspect(row)
    inspect(row.get("independent_projection"))
    lanes = row.get("pricing_lanes")
    if lanes is not None and not isinstance(lanes, dict):
        invalid_ev = True
    elif isinstance(lanes, dict):
        inspect(lanes.get("lane_a_independent"))
        inspect(lanes.get("lane_b_anchored"))
    reason = (
        "GAME_PROBABILITY_CLAIM_INVALID" if invalid_p else
        "GAME_EV_CLAIM_INVALID" if invalid_ev else
        "EXTREME_CLAIMED_EV_QUARANTINE" if any(
            ev >= EXTREME_CLAIMED_EV_QUARANTINE for ev in evs
        ) else None
    )
    return reason, max(evs) if evs else None


def quarantine_game_surfaces(surfaces):
    """Quarantine an input index across ALL ranked surfaces if ANY claim fails.

    Research-only output partition; original rows are never changed. This
    helper has no independent evaluated_rows and cannot authenticate evidence.
    """
    if not isinstance(surfaces, dict):
        raise ValueError("GAME_SURFACES_NOT_OBJECT")
    rows_by_surface = {}
    holds = {}
    priority = ("GAME_PROBABILITY_CLAIM_INVALID", "GAME_EV_CLAIM_INVALID",
                "EXTREME_CLAIMED_EV_QUARANTINE")
    for name in GAME_SURFACES:
        rows = surfaces.get(name, ())
        if not isinstance(rows, (list, tuple)):
            raise ValueError("GAME_SURFACE_NOT_LIST:" + name)
        rows_by_surface[name] = rows
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("GAME_SURFACE_ROW_NOT_OBJECT")
            idx = row.get("input_index")
            if type(idx) is not int or idx < 0:
                raise ValueError("GAME_SURFACE_INPUT_INDEX_INVALID")
            if idx in seen:
                raise ValueError("GAME_SURFACE_DUPLICATE_INPUT_INDEX")
            seen.add(idx)
            reason, max_ev = game_claim_hold(row)
            if reason is None:
                continue
            if idx not in holds:
                holds[idx] = {"reason": reason, "max_ev": max_ev,
                              "source_status": row.get("status")}
            else:
                old = holds[idx]
                old["reason"] = next(r for r in priority
                                     if r in (old["reason"], reason))
                vals = [v for v in (old["max_ev"], max_ev) if v is not None]
                old["max_ev"] = max(vals) if vals else None
    filtered = {}
    quarantined = {}
    for name, rows in rows_by_surface.items():
        kept = []
        for row in rows:
            idx = row["input_index"]
            hold = holds.get(idx)
            if hold is None:
                kept.append(row)
                continue
            if idx not in quarantined:
                quarantined[idx] = {
                    "input_index": idx,
                    "source_surfaces": [],
                    "source_status": hold["source_status"],
                    "reason": hold["reason"],
                    "max_finite_claimed_ev": hold["max_ev"],
                    "research_only": True,
                    "eligible_for_headline": False,
                    "eligible_for_forward_clock": False,
                }
            quarantined[idx]["source_surfaces"].append(name)
        filtered[name] = kept
    return filtered, list(quarantined.values())
