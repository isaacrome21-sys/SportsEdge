"""Fail-closed output partition for unvalidated phone prop research rows.

This is the owner's EXISTING >=+40% claimed-EV quarantine, not a model
calibration change. It does not edit, erase, grade, or authorize any row.
The caller must preserve the original evaluated_rows for append-only grading.
"""
from __future__ import annotations

import math

EXTREME_CLAIMED_EV_QUARANTINE = 0.40
CANDIDATE_STATUS = "RESEARCH_CANDIDATE_NOT_VALIDATED"


def _finite_ev(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _claims(row):
    """Inspect both the visible and hidden raw/anchored claims.

    A small blended EV must not hide a >=40% independent claim. An explicitly
    malformed EV claim cannot be silently discarded to create a candidate.
    """
    values = []
    invalid = False
    invalid_probability = False

    def add(source, fields):
        nonlocal invalid, invalid_probability
        # Explicit impossible probabilities must not reach the raw candidate
        # surface merely because the visible EV is small. Missing fields are
        # not synthesized: this output guard is not a model validator.
        for key in ("estimate_p", "model_probability"):
            if key in source and source[key] is not None:
                probability = _finite_ev(source[key])
                if probability is None or not 0 <= probability <= 1:
                    invalid_probability = True
        for field in fields:
            if field not in source or source[field] is None:
                continue
            number = _finite_ev(source[field])
            if number is None:
                invalid = True
            else:
                values.append(number)

    add(row, ("ev_per_dollar", "raw_ev_per_dollar", "reported_ev_per_dollar"))
    independent = row.get("independent_projection")
    if independent is not None:
        if isinstance(independent, dict):
            add(independent, ("ev_per_dollar", "raw_ev_per_dollar",
                              "reported_ev_per_dollar"))
        else:
            invalid = True
    lanes = row.get("pricing_lanes")
    if lanes is not None:
        if not isinstance(lanes, dict):
            invalid = True
        else:
            for name in ("lane_a_independent", "lane_b_anchored"):
                lane = lanes.get(name)
                if lane is not None:
                    if isinstance(lane, dict):
                        add(lane, ("ev_per_dollar", "raw_ev_per_dollar",
                                   "reported_ev_per_dollar"))
                    else:
                        invalid = True
    return values, invalid, invalid_probability


def partition_prop_surfaces(modeled_props):
    """Return (candidates, watchlist, quarantine), preserving original rows.

    Only the two research-facing prop lists are filtered. The quarantine
    ledger references original input indices; evaluated_rows is never mutated
    or removed, and no retrospective grading or CLV eligibility is granted.
    """
    candidates, watchlist, quarantine = [], [], []
    for row in modeled_props:
        status = str(row.get("status") or "")
        candidate = status == CANDIDATE_STATUS
        watch = status.startswith("WATCH_")
        if not (candidate or watch):
            continue

        values, invalid, invalid_probability = _claims(row)
        visible = _finite_ev(row.get("ev_per_dollar"))
        if candidate and visible is None:
            invalid = True
        reason = ("PROP_PROBABILITY_CLAIM_INVALID" if invalid_probability else
                  "PROP_EV_CLAIM_INVALID" if invalid else
                  "EXTREME_CLAIMED_EV_QUARANTINE" if any(
                      value >= EXTREME_CLAIMED_EV_QUARANTINE for value in values
                  ) else None)
        if reason:
            quarantine.append({
                "input_index": row.get("input_index"),
                "source_status": status,
                "reason": reason,
                "max_finite_claimed_ev": max(values) if values else None,
                "research_only": True,
                "eligible_for_headline": False,
                "eligible_for_forward_clock": False,
            })
        elif candidate:
            candidates.append(row)
        else:
            watchlist.append(row)

    candidates.sort(key=lambda row: -_finite_ev(row["ev_per_dollar"]))
    watchlist.sort(key=lambda row: -(
        _finite_ev(row.get("ev_per_dollar"))
        if _finite_ev(row.get("ev_per_dollar")) is not None else -1
    ))
    return candidates, watchlist, quarantine
