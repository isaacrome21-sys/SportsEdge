"""Executable preregistered CFB candidate-family primitives.

This module contains no evaluation results and consumes no model-selection attempt.
It implements only the EQUAL_WEIGHT_HARD_SWITCH baseline on top of the existing
CFB_JOINT_GAME_FEATURES_V1 row contract. The other three frozen families remain
intentionally unimplemented until their complete constants/formulas are
preregistered before any evaluation.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

FAMILY_EQUAL_WEIGHT_HARD_SWITCH = "EQUAL_WEIGHT_HARD_SWITCH"
IMPLEMENTED_FAMILIES = frozenset({FAMILY_EQUAL_WEIGHT_HARD_SWITCH})

TEAM_METRIC_KEYS = (
    "off_ppa_rush",
    "off_ppa_dropback",
    "def_ppa_rush_allowed",
    "def_ppa_dropback_allowed",
    "off_success_rate",
    "def_success_rate_allowed",
    "standard_down_ppa",
    "passing_down_success_rate",
    "eckel_rate",
    "points_per_eckel",
    "points_per_drive",
    "net_field_position",
    "explosive_rate",
)

BANNED_MARKET_KEYS = frozenset({
    "spread", "spread_line", "total", "total_line", "line", "price",
    "american_odds", "decimal_odds", "implied_probability", "implied_prob",
    "market_probability", "novig_prob", "no_vig_prob", "book", "sportsbook",
    "closing_line", "closing_price", "home_moneyline", "away_moneyline", "odds",
})


class CFBCandidateFamilyError(ValueError):
    pass


def _assert_market_blind(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key).strip().lower()
            if name in BANNED_MARKET_KEYS or "implied_prob" in name or "novig" in name or "no_vig" in name:
                raise CFBCandidateFamilyError(f"CFB_CANDIDATE_MARKET_DATA_PROHIBITED:{path}.{key}")
            _assert_market_blind(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for idx, child in enumerate(value):
            _assert_market_blind(child, f"{path}[{idx}]")


def _metrics(row: Mapping[str, Any], side: str) -> Mapping[str, Any]:
    metrics = row.get(f"{side}_metrics")
    if not isinstance(metrics, Mapping):
        raise CFBCandidateFamilyError(f"CFB_CANDIDATE_{side.upper()}_METRICS_REQUIRED")
    missing = [key for key in TEAM_METRIC_KEYS if key not in metrics]
    if missing:
        raise CFBCandidateFamilyError(
            f"CFB_CANDIDATE_METRIC_FIELDS_MISSING:{side}:{','.join(missing)}"
        )
    return metrics


def materialize_equal_weight_hard_switch(row: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return the frozen baseline candidate row.

    Source switch:
    * Week 1 -> immediately prior season, PRIOR_SEASON_FALLBACK.
    * Week 2+ -> same season through exactly week-1, CURRENT_SEASON_PRIOR_WEEKS.

    "Equal weight" means this family adds no candidate-specific feature weights:
    the existing CFB_JOINT_GAME_FEATURES_V1 standardized feature vector and the
    existing temporal ridge policy remain unchanged. This function performs no
    fitting and sees no outcomes other than fields already present in the row.
    """
    _assert_market_blind({
        key: value for key, value in row.items()
        if key not in {"home_score", "away_score", "regulation_home_score", "regulation_away_score"}
    })
    try:
        season = int(row["season"])
        week = int(row["week"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CFBCandidateFamilyError("CFB_CANDIDATE_SEASON_WEEK_INVALID") from exc
    if week < 1:
        raise CFBCandidateFamilyError("CFB_CANDIDATE_WEEK_INVALID")

    for side in ("home", "away"):
        metrics = _metrics(row, side)
        try:
            metric_season = int(metrics["season"])
            through_week = int(metrics["through_week"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CFBCandidateFamilyError(
                f"CFB_CANDIDATE_{side.upper()}_METRIC_IDENTITY_INVALID"
            ) from exc
        source = str(metrics.get("sample_source") or "").upper()

        if week == 1:
            if source != "PRIOR_SEASON_FALLBACK" or metric_season != season - 1:
                raise CFBCandidateFamilyError(
                    f"CFB_CANDIDATE_WEEK1_PRIOR_SEASON_SWITCH_INVALID:{side}"
                )
        else:
            if (
                source != "CURRENT_SEASON_PRIOR_WEEKS"
                or metric_season != season
                or through_week != week - 1
            ):
                raise CFBCandidateFamilyError(
                    f"CFB_CANDIDATE_CURRENT_SEASON_SWITCH_INVALID:{side}"
                )

    return deepcopy(dict(row))


def materialize_candidate_row(
    family: str,
    row: Mapping[str, Any],
    *,
    constants: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Dispatch only to fully implemented preregistration families.

    Unknown/unimplemented families fail closed. Supplying constants to the
    baseline is also rejected so no hidden tuning can enter the baseline bytes.
    """
    if family == FAMILY_EQUAL_WEIGHT_HARD_SWITCH:
        if constants not in (None, {}):
            raise CFBCandidateFamilyError("CFB_EQUAL_WEIGHT_BASELINE_CONSTANTS_PROHIBITED")
        return materialize_equal_weight_hard_switch(row)
    raise CFBCandidateFamilyError(f"CFB_CANDIDATE_FAMILY_UNIMPLEMENTED:{family}")


__all__ = [
    "CFBCandidateFamilyError",
    "FAMILY_EQUAL_WEIGHT_HARD_SWITCH",
    "IMPLEMENTED_FAMILIES",
    "TEAM_METRIC_KEYS",
    "materialize_candidate_row",
    "materialize_equal_weight_hard_switch",
]
