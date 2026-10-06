"""Research-only composite feature contract for the next MLB pitcher-K candidate.

The current production pitcher-K price remains unchanged. This module only binds
already-frozen workload, opponent-K, and lineup-K research/validated components
into one auditable candidate record and declares what is still missing before an
untouched PIT evaluation may be attempted.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping, Sequence

AUTHORITY = "RESEARCH_ONLY_NOT_MODEL_INPUT_NOT_DEPLOYED"
SCHEMA = "MLB_PITCHER_K_COMPOSITE_CANDIDATE_V1"
WORKLOAD_SCHEMA = "MLB_PITCHER_K_WORKLOAD_CANDIDATE_V1"
OPP_K_VALIDATED_IN = "#1509"
LINEUP_K_VALIDATED_IN = "#1540"
OPP_K_BETA = 1.0
LINEUP_W = 200.0
LINEUP_GAMMA = 0.5

MISSING_SKILL_COMPONENTS = (
    "pitcher_whiff_chase_pit_source",
    "pitcher_handedness_pit_source",
)


class PitcherKCompositeCandidateError(ValueError):
    pass


def _positive_number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise PitcherKCompositeCandidateError(f"{name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PitcherKCompositeCandidateError(f"{name} must be numeric") from exc
    if not isfinite(number) or number <= 0:
        raise PitcherKCompositeCandidateError(f"{name} must be positive")
    return number


def _aligned_positive(values: Any, *, n: int, name: str) -> list[float]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise PitcherKCompositeCandidateError(f"{name} must be a sequence")
    if len(values) != n:
        raise PitcherKCompositeCandidateError(f"{name} must align with workload history")
    return [_positive_number(value, f"{name}[{i}]") for i, value in enumerate(values)]


def _validate_workload(workload: Mapping[str, Any]) -> tuple[int, dict[str, Any]]:
    if not isinstance(workload, Mapping):
        raise PitcherKCompositeCandidateError("workload bundle required")
    if workload.get("schema") != WORKLOAD_SCHEMA:
        raise PitcherKCompositeCandidateError("unexpected workload schema")
    if workload.get("authority") != AUTHORITY:
        raise PitcherKCompositeCandidateError("workload authority must remain research only")
    if workload.get("deployment") is not False or workload.get("model_p_eligible") is not False:
        raise PitcherKCompositeCandidateError("workload bundle cannot be deployed/model eligible")
    try:
        n = int(workload.get("start_count"))
    except (TypeError, ValueError) as exc:
        raise PitcherKCompositeCandidateError("workload start_count invalid") from exc
    history = workload.get("history")
    if not 5 <= n <= 10 or not isinstance(history, list) or len(history) != n:
        raise PitcherKCompositeCandidateError("workload must contain 5..10 aligned prior starts")
    summary = workload.get("summary")
    if not isinstance(summary, Mapping):
        raise PitcherKCompositeCandidateError("workload summary required")
    required = (
        "recent_mean_batters_faced",
        "recent_mean_number_of_pitches",
        "recent_mean_outs",
        "recent_mean_k_per_batter_faced",
        "recent_mean_pitches_per_batter_faced",
    )
    clean_summary = {key: _positive_number(summary.get(key), f"workload.summary.{key}") for key in required}
    return n, clean_summary


def _validate_opp_k(opp_k: Mapping[str, Any], *, n: int) -> dict[str, Any]:
    if not isinstance(opp_k, Mapping):
        raise PitcherKCompositeCandidateError("opponent-K adjustment required")
    if str(opp_k.get("market") or "").upper() != "PITCHER_K":
        raise PitcherKCompositeCandidateError("opponent-K market must be PITCHER_K")
    beta = _positive_number(opp_k.get("beta"), "opp_k.beta")
    if abs(beta - OPP_K_BETA) > 1e-12:
        raise PitcherKCompositeCandidateError("unvalidated opponent-K beta")
    if opp_k.get("validated_in") != OPP_K_VALIDATED_IN:
        raise PitcherKCompositeCandidateError("opponent-K validation identity mismatch")
    target_rel = _positive_number(opp_k.get("target_rel"), "opp_k.target_rel")
    history_rel = _aligned_positive(opp_k.get("history_rel"), n=n, name="opp_k.history_rel")
    try:
        opponent_team_id = int(opp_k.get("opponent_team_id"))
    except (TypeError, ValueError) as exc:
        raise PitcherKCompositeCandidateError("opponent_team_id required") from exc
    if opponent_team_id <= 0:
        raise PitcherKCompositeCandidateError("opponent_team_id required")
    return {
        "market": "PITCHER_K",
        "beta": beta,
        "target_rel": target_rel,
        "history_rel": history_rel,
        "opponent_team_id": opponent_team_id,
        "validated_in": OPP_K_VALIDATED_IN,
    }


def _validate_lineup_k(lineup_k: Mapping[str, Any] | None, *, n: int) -> dict[str, Any] | None:
    if lineup_k is None:
        return None
    if not isinstance(lineup_k, Mapping):
        raise PitcherKCompositeCandidateError("lineup-K adjustment must be an object")
    w = _positive_number(lineup_k.get("W"), "lineup_k.W")
    gamma = _positive_number(lineup_k.get("gamma"), "lineup_k.gamma")
    if abs(w - LINEUP_W) > 1e-12 or abs(gamma - LINEUP_GAMMA) > 1e-12:
        raise PitcherKCompositeCandidateError("unvalidated lineup-K parameters")
    if lineup_k.get("validated_in") != LINEUP_K_VALIDATED_IN:
        raise PitcherKCompositeCandidateError("lineup-K validation identity mismatch")
    target = _positive_number(lineup_k.get("target_deviation"), "lineup_k.target_deviation")
    history = _aligned_positive(
        lineup_k.get("history_deviation"),
        n=n,
        name="lineup_k.history_deviation",
    )
    return {
        "W": w,
        "gamma": gamma,
        "target_deviation": target,
        "history_deviation": history,
        "validated_in": LINEUP_K_VALIDATED_IN,
    }


def build_composite_candidate(
    *,
    workload: Mapping[str, Any],
    opp_k_adjustment: Mapping[str, Any],
    lineup_k_adjustment: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Bind frozen components without creating a probability or evaluation result."""
    n, workload_summary = _validate_workload(workload)
    opp_k = _validate_opp_k(opp_k_adjustment, n=n)
    lineup_k = _validate_lineup_k(lineup_k_adjustment, n=n)
    missing = list(MISSING_SKILL_COMPONENTS)
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "market": "PITCHER_K",
        "start_count": n,
        "components": {
            "workload_leash": {
                "schema": WORKLOAD_SCHEMA,
                "summary": workload_summary,
            },
            "opponent_k": opp_k,
            "lineup_k": lineup_k,
        },
        "lineup_status": "VALIDATED_COMPONENT_PRESENT" if lineup_k is not None else "VALIDATED_FALLBACK_TO_OPP_K",
        "missing_components": missing,
        "evaluation_ready": False,
        "deployment": False,
        "model_p_eligible": False,
        "probability_formula": None,
        "fit_parameters": None,
    }


def assert_evaluation_ready(candidate: Mapping[str, Any]) -> None:
    """Fail closed until a later preregistered PIT-safe skill-source PR fills the gap."""
    if not isinstance(candidate, Mapping) or candidate.get("schema") != SCHEMA:
        raise PitcherKCompositeCandidateError("unexpected composite candidate")
    missing = candidate.get("missing_components")
    if missing:
        raise PitcherKCompositeCandidateError(
            "PITCHER_K_COMPOSITE_NOT_EVALUATION_READY:" + ",".join(map(str, missing))
        )
    if candidate.get("evaluation_ready") is not True:
        raise PitcherKCompositeCandidateError("PITCHER_K_COMPOSITE_NOT_EVALUATION_READY")
