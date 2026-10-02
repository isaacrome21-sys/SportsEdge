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
FAMILY_RELIABILITY_WEIGHTED_HARD_SWITCH = "RELIABILITY_WEIGHTED_HARD_SWITCH"
FAMILY_PRIOR_CURRENT_BLEND = "PRIOR_CURRENT_BLEND"
FAMILY_GAMES_IN_SAMPLE_FEATURE = "GAMES_IN_SAMPLE_FEATURE"
IMPLEMENTED_FAMILIES = frozenset({FAMILY_EQUAL_WEIGHT_HARD_SWITCH,FAMILY_RELIABILITY_WEIGHTED_HARD_SWITCH,FAMILY_PRIOR_CURRENT_BLEND,FAMILY_GAMES_IN_SAMPLE_FEATURE})

TEAM_METRIC_KEYS = (
    "off_ppa_rush",
    "off_ppa_dropback",
    "def_ppa_rush_allowed",
    "def_ppa_dropback_allowed",
    "off_success_rate",
    "def_success_rate_allowed",
    "standard_down_ppa",
    "passing_down_success_rate",
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
    * Week 0/1 -> immediately prior season, PRIOR_SEASON_FALLBACK.
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
    if week < 0:
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

        if week <= 1:
            if source != "PRIOR_SEASON_FALLBACK" or metric_season != season - 1:
                raise CFBCandidateFamilyError(
                    f"CFB_CANDIDATE_EARLY_PRIOR_SEASON_SWITCH_INVALID:{side}"
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


def _dual_metrics(row: Mapping[str, Any], side: str):
    prior=row.get(f"{side}_prior_metrics"); current=row.get(f"{side}_current_metrics")
    if not isinstance(prior, Mapping) or not isinstance(current, Mapping):
        raise CFBCandidateFamilyError(f"CFB_CANDIDATE_DUAL_SNAPSHOT_REQUIRED:{side}")
    missing=[k for k in TEAM_METRIC_KEYS if k not in prior or k not in current]
    if missing: raise CFBCandidateFamilyError(f"CFB_CANDIDATE_DUAL_METRIC_FIELDS_MISSING:{side}:{','.join(missing)}")
    games=int(current.get("games_in_sample",0))
    if games<0: raise CFBCandidateFamilyError(f"CFB_CANDIDATE_GAMES_IN_SAMPLE_INVALID:{side}")
    return prior,current,games

def _replace_metrics(row, chooser):
    out=deepcopy(dict(row)); _assert_market_blind(out)
    for side in ("home","away"):
        prior,current,games=_dual_metrics(out,side); chosen=dict(chooser(prior,current,games)); chosen["games_in_sample"]=games; out[f"{side}_metrics"]=chosen
    return out

def materialize_reliability_weighted_hard_switch(row, *, min_current_games=3):
    if min_current_games!=3: raise CFBCandidateFamilyError("CFB_RELIABILITY_CONSTANT_MISMATCH")
    return _replace_metrics(row,lambda p,c,g:c if g>=3 else p)

def materialize_prior_current_blend(row, *, prior_equivalent_games=4.0):
    if float(prior_equivalent_games)!=4.0: raise CFBCandidateFamilyError("CFB_BLEND_CONSTANT_MISMATCH")
    def choose(p,c,g):
        w=g/(g+4.0); out=dict(c)
        for k in TEAM_METRIC_KEYS: out[k]=w*float(c[k])+(1-w)*float(p[k])
        return out
    return _replace_metrics(row,choose)

def materialize_games_in_sample_feature(row, *, cap=12, divisor=12):
    if cap!=12 or divisor!=12: raise CFBCandidateFamilyError("CFB_GAMES_IN_SAMPLE_CONSTANT_MISMATCH")
    out=_replace_metrics(row,lambda p,c,g:c if g>0 else p)
    for side in ("home","away"): out[f"{side}_games_in_sample_feature"]=min(int(out[f"{side}_metrics"]["games_in_sample"]),12)/12.0
    return out

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
    constants=dict(constants or {})
    if family==FAMILY_EQUAL_WEIGHT_HARD_SWITCH:
        if constants: raise CFBCandidateFamilyError("CFB_EQUAL_WEIGHT_BASELINE_CONSTANTS_PROHIBITED")
        return materialize_equal_weight_hard_switch(row)
    if family==FAMILY_RELIABILITY_WEIGHTED_HARD_SWITCH: return materialize_reliability_weighted_hard_switch(row,min_current_games=int(constants.get("min_current_games",3)))
    if family==FAMILY_PRIOR_CURRENT_BLEND: return materialize_prior_current_blend(row,prior_equivalent_games=float(constants.get("prior_equivalent_games",4.0)))
    if family==FAMILY_GAMES_IN_SAMPLE_FEATURE: return materialize_games_in_sample_feature(row,cap=int(constants.get("games_in_sample_cap",12)),divisor=int(constants.get("normalization_divisor",12)))
    raise CFBCandidateFamilyError(f"CFB_CANDIDATE_FAMILY_UNIMPLEMENTED:{family}")


__all__ = [
    "CFBCandidateFamilyError",
    "FAMILY_EQUAL_WEIGHT_HARD_SWITCH",
    "IMPLEMENTED_FAMILIES",
    "TEAM_METRIC_KEYS",
    "materialize_candidate_row",
    "materialize_equal_weight_hard_switch",
]
