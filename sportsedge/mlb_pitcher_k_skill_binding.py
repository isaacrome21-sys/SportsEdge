"""Research-only binding of PIT-safe Statcast skill observations to pitcher-K candidate.

This module does not price a market. It binds a main-provenance Statcast pitcher
context to the composite candidate and keeps evaluation closed until a separate
probability formula and untouched evaluation protocol are frozen.
"""
from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any, Mapping

from .mlb_pitcher_k_composite_candidate import (
    AUTHORITY,
    SCHEMA as COMPOSITE_SCHEMA,
)

SCHEMA = "MLB_PITCHER_K_SKILL_BOUND_CANDIDATE_V1"


class PitcherKSkillBindingError(ValueError):
    pass


def _rate(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise PitcherKSkillBindingError(f"{name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PitcherKSkillBindingError(f"{name} must be numeric") from exc
    if not isfinite(number) or not 0.0 <= number <= 1.0:
        raise PitcherKSkillBindingError(f"{name} outside [0,1]")
    return number


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise PitcherKSkillBindingError(f"{name} must be integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise PitcherKSkillBindingError(f"{name} must be integer") from exc
    if number <= 0:
        raise PitcherKSkillBindingError(f"{name} must be positive")
    return number


def _validate_provenance(provenance: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(provenance, Mapping):
        raise PitcherKSkillBindingError("main provenance receipt required")
    if provenance.get("schema") != "SPORTSEDGE_STATCAST_MAIN_PROVENANCE_V1":
        raise PitcherKSkillBindingError("unexpected Statcast provenance schema")
    if provenance.get("ref") != "refs/heads/main":
        raise PitcherKSkillBindingError("Statcast source was not captured from main")
    if provenance.get("head_branch") != "main":
        raise PitcherKSkillBindingError("Statcast head branch must be main")
    if provenance.get("eligible_for_forward_evaluation") is not True:
        raise PitcherKSkillBindingError("Statcast provenance is not forward-evaluation eligible")
    head_sha = str(provenance.get("head_sha") or "").strip()
    run_id = str(provenance.get("run_id") or "").strip()
    if len(head_sha) != 40 or not run_id:
        raise PitcherKSkillBindingError("Statcast provenance identity incomplete")
    return {
        "schema": provenance["schema"],
        "run_id": run_id,
        "event_name": provenance.get("event_name"),
        "ref": "refs/heads/main",
        "head_branch": "main",
        "head_sha": head_sha,
        "eligible_for_forward_evaluation": True,
    }


def bind_statcast_skill(
    candidate: Mapping[str, Any],
    *,
    pitcher_context: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(candidate, Mapping) or candidate.get("schema") != COMPOSITE_SCHEMA:
        raise PitcherKSkillBindingError("unexpected composite candidate")
    if candidate.get("authority") != AUTHORITY:
        raise PitcherKSkillBindingError("candidate authority must remain research only")
    if candidate.get("deployment") is not False or candidate.get("model_p_eligible") is not False:
        raise PitcherKSkillBindingError("candidate cannot already be deployed/model eligible")
    if not isinstance(pitcher_context, Mapping):
        raise PitcherKSkillBindingError("pitcher Statcast context required")

    whiff_rate = _rate(pitcher_context.get("whiff_rate"), "whiff_rate")
    chase_rate = _rate(pitcher_context.get("chase_rate"), "chase_rate")
    swings = _positive_int(pitcher_context.get("swings"), "swings")
    whiffs = _positive_int(pitcher_context.get("whiffs"), "whiffs")
    out_zone = _positive_int(pitcher_context.get("out_of_zone_pitches"), "out_of_zone_pitches")
    chases = _positive_int(pitcher_context.get("chases"), "chases")
    hand = str(pitcher_context.get("pitcher_hand") or "").upper()
    if hand not in {"L", "R"}:
        raise PitcherKSkillBindingError("pitcher_hand must be L or R")
    if whiffs > swings:
        raise PitcherKSkillBindingError("whiffs cannot exceed swings")
    if chases > out_zone:
        raise PitcherKSkillBindingError("chases cannot exceed out_of_zone_pitches")
    if abs(whiff_rate - whiffs / swings) > 1e-6:
        raise PitcherKSkillBindingError("whiff_rate does not match counts")
    if abs(chase_rate - chases / out_zone) > 1e-6:
        raise PitcherKSkillBindingError("chase_rate does not match counts")

    window_start = str(pitcher_context.get("window_start") or "").strip()
    window_end = str(pitcher_context.get("window_end") or "").strip()
    if not window_start or not window_end:
        raise PitcherKSkillBindingError("Statcast window identity required")

    proof = _validate_provenance(provenance)
    out = deepcopy(dict(candidate))
    out["schema"] = SCHEMA
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
        "window_start": window_start,
        "window_end": window_end,
        "provenance": proof,
    }
    out["missing_components"] = []
    out["source_complete"] = True
    out["evaluation_ready"] = False
    out["evaluation_blocker"] = "PROBABILITY_FORMULA_AND_UNTOUCHED_EVALUATION_PROTOCOL_NOT_FROZEN"
    out["deployment"] = False
    out["model_p_eligible"] = False
    out["probability_formula"] = None
    out["fit_parameters"] = None
    return out
