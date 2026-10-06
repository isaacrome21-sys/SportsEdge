"""Validator for the frozen MLB pitcher-K probability-candidate preregistration.

This module does not fit a model, inspect outcomes, or price a sportsbook market. It
only makes the pre-scoring contract machine-checkable.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping, Sequence

SCHEMA = "MLB_PITCHER_K_PROBABILITY_PREREG_V1"
CANDIDATE_FAMILY = "RIDGE_LOGIT_K_RATE_BETA_BINOMIAL_V1"
INPUT_SCHEMA = "MLB_PITCHER_K_SKILL_BOUND_CANDIDATE_V1"
FEATURES = (
    "recent_mean_batters_faced",
    "recent_mean_k_per_batter_faced",
    "recent_mean_pitches_per_batter_faced",
    "opponent_target_rel",
    "lineup_target_deviation_or_1",
    "whiff_rate",
    "chase_rate",
    "pitcher_hand_R",
)
TRAINING = (2023,)
VALIDATION = (2024,)
CANDIDATE_TEST = (2025,)
RIDGE_GRID = (0.1, 1.0, 10.0, 100.0)
CONCENTRATION_GRID = (20.0, 50.0, 100.0, 200.0, 1000000000.0)


class PitcherKProbabilityPreregError(ValueError):
    pass


def _years(value: Any, name: str) -> tuple[int, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PitcherKProbabilityPreregError(f"{name} must be a sequence")
    try:
        years = tuple(int(v) for v in value)
    except (TypeError, ValueError) as exc:
        raise PitcherKProbabilityPreregError(f"{name} must be integer years") from exc
    if not years or len(set(years)) != len(years):
        raise PitcherKProbabilityPreregError(f"{name} invalid")
    return years


def _numbers(value: Any, name: str) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PitcherKProbabilityPreregError(f"{name} must be a sequence")
    out = []
    for raw in value:
        if isinstance(raw, bool):
            raise PitcherKProbabilityPreregError(f"{name} must be numeric")
        try:
            number = float(raw)
        except (TypeError, ValueError) as exc:
            raise PitcherKProbabilityPreregError(f"{name} must be numeric") from exc
        if not isfinite(number) or number <= 0:
            raise PitcherKProbabilityPreregError(f"{name} must be positive finite")
        out.append(number)
    return tuple(out)


def validate_pitcher_k_probability_prereg(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PitcherKProbabilityPreregError("prereg object required")
    if value.get("schema") != SCHEMA:
        raise PitcherKProbabilityPreregError("unexpected prereg schema")
    if value.get("status") != "FROZEN_BEFORE_CANDIDATE_SCORING":
        raise PitcherKProbabilityPreregError("prereg must be frozen before scoring")
    if value.get("market") != "PITCHER_K":
        raise PitcherKProbabilityPreregError("market must be PITCHER_K")
    if value.get("candidate_family") != CANDIDATE_FAMILY:
        raise PitcherKProbabilityPreregError("candidate family mismatch")
    if value.get("input_schema") != INPUT_SCHEMA:
        raise PitcherKProbabilityPreregError("input schema mismatch")

    authority = value.get("authority")
    if not isinstance(authority, Mapping) or not authority:
        raise PitcherKProbabilityPreregError("zero-authority declaration required")
    if any(bool(v) for v in authority.values()):
        raise PitcherKProbabilityPreregError("prereg cannot grant authority")

    data = value.get("data")
    if not isinstance(data, Mapping):
        raise PitcherKProbabilityPreregError("data contract required")
    train = _years(data.get("training_seasons"), "training_seasons")
    validation = _years(data.get("validation_seasons"), "validation_seasons")
    test = _years(data.get("candidate_test_seasons"), "candidate_test_seasons")
    if train != TRAINING or validation != VALIDATION or test != CANDIDATE_TEST:
        raise PitcherKProbabilityPreregError("season split changed")
    if set(train) & set(validation) or set(train) & set(test) or set(validation) & set(test):
        raise PitcherKProbabilityPreregError("season split overlaps")
    if data.get("game_type") != "R":
        raise PitcherKProbabilityPreregError("regular-season-only development required")
    if data.get("same_day_and_future_rows_forbidden") is not True:
        raise PitcherKProbabilityPreregError("PIT guard required")
    if data.get("sportsbook_prices_forbidden_from_fit") is not True:
        raise PitcherKProbabilityPreregError("sportsbook inputs must be forbidden")
    if data.get("market_consensus_forbidden_from_fit") is not True:
        raise PitcherKProbabilityPreregError("market consensus inputs must be forbidden")
    if data.get("candidate_test_is_broader_promotion_evidence") is not False:
        raise PitcherKProbabilityPreregError("historical candidate test cannot create promotion authority")

    features = tuple(value.get("features") or ())
    if features != FEATURES:
        raise PitcherKProbabilityPreregError("feature set changed")
    if any("price" in str(name).lower() or "odds" in str(name).lower() for name in features):
        raise PitcherKProbabilityPreregError("market feature contamination")

    formula = value.get("formula")
    if not isinstance(formula, Mapping):
        raise PitcherKProbabilityPreregError("formula contract required")
    if formula.get("rate_model") != "BINOMIAL_LOGIT_RIDGE":
        raise PitcherKProbabilityPreregError("rate model changed")
    if formula.get("count_distribution") != "BETA_BINOMIAL":
        raise PitcherKProbabilityPreregError("count distribution changed")
    if _numbers(formula.get("ridge_alpha_grid"), "ridge_alpha_grid") != RIDGE_GRID:
        raise PitcherKProbabilityPreregError("ridge grid changed")
    if _numbers(formula.get("concentration_grid"), "concentration_grid") != CONCENTRATION_GRID:
        raise PitcherKProbabilityPreregError("concentration grid changed")
    if formula.get("alpha_selection") != "LOWEST_2024_MEAN_RPS_TIE_LARGER_ALPHA":
        raise PitcherKProbabilityPreregError("alpha selection changed")
    if formula.get("concentration_selection") != "LOWEST_2024_MEAN_RPS_TIE_LARGER_CONCENTRATION":
        raise PitcherKProbabilityPreregError("concentration selection changed")
    if formula.get("refit_after_selection") != "REFIT_2023_2024_ONLY":
        raise PitcherKProbabilityPreregError("refit boundary changed")

    evaluation = value.get("evaluation")
    if not isinstance(evaluation, Mapping):
        raise PitcherKProbabilityPreregError("evaluation contract required")
    if evaluation.get("primary_metric") != "MEAN_RPS_HALF_LINES_0_5_TO_19_5":
        raise PitcherKProbabilityPreregError("primary metric changed")
    if int(evaluation.get("min_candidate_test_starts", 0)) < 500:
        raise PitcherKProbabilityPreregError("candidate test minimum too small")
    bootstrap = evaluation.get("bootstrap")
    if not isinstance(bootstrap, Mapping):
        raise PitcherKProbabilityPreregError("bootstrap contract required")
    if bootstrap.get("unit") != "PITCHER_ID" or int(bootstrap.get("reps", 0)) != 2000:
        raise PitcherKProbabilityPreregError("bootstrap contract changed")
    if int(bootstrap.get("seed", -1)) != 20261006 or float(bootstrap.get("ci", 0)) != 0.95:
        raise PitcherKProbabilityPreregError("bootstrap identity changed")

    prohibitions = set(map(str, value.get("prohibitions") or ()))
    required = {
        "NO_2025_PARAMETER_TUNING",
        "NO_SPORTSBOOK_PRICE_FEATURES",
        "NO_POST_OUTCOME_FORMULA_EDIT_WITHOUT_NEW_CANDIDATE_ID",
        "NO_MODEL_P_OR_OFFICIAL_AUTHORITY_FROM_THIS_PREREG",
        "NO_BACKFILL_AS_FORWARD_EVIDENCE",
    }
    if not required.issubset(prohibitions):
        raise PitcherKProbabilityPreregError("required prohibitions missing")

    return {
        "schema": SCHEMA,
        "candidate_family": CANDIDATE_FAMILY,
        "training_seasons": list(train),
        "validation_seasons": list(validation),
        "candidate_test_seasons": list(test),
        "features": list(features),
        "ready_for_training_only_fit": True,
        "authority": dict(authority),
    }
