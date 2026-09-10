"""Audit whether captured historical release schemas can satisfy frozen CFB inputs.

This module is intentionally descriptive only.  A field being derivable here does
not prove point-in-time availability, and a missing field must not be imputed merely
to make the historical materializer run.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable, Mapping, Any


CFB_HISTORY_SCHEMA_COMPAT_V1 = "CFB_HISTORY_SCHEMA_COMPAT_V1"

# Frozen CFBTeamMetrics fields consumed by the historical materializer/model.
REQUIRED_TEAM_METRICS = (
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

# Exact source-column recipes.  Opponent-derived fields require an explicit game
# join, but still come from predictive source rows rather than sportsbook data.
RECIPES: dict[str, tuple[tuple[str, str], ...]] = {
    "off_ppa_rush": (("adv_team", "EPA_rushing_per_play"),),
    "off_ppa_dropback": (("adv_team", "EPA_passing_per_play"),),
    "def_ppa_rush_allowed": (("adv_team_opponent_join", "EPA_rushing_per_play"),),
    "def_ppa_dropback_allowed": (("adv_team_opponent_join", "EPA_passing_per_play"),),
    "off_success_rate": (("adv_situational", "EPA_success_rate"),),
    "def_success_rate_allowed": (("adv_situational_opponent_join", "EPA_success_rate"),),
    "standard_down_ppa": (("adv_situational", "EPA_standard_down_per_play"),),
    "passing_down_success_rate": (("adv_situational", "EPA_success_passing_down_rate"),),
    "eckel_rate": (),
    "points_per_eckel": (),
    "points_per_drive": (),
    "net_field_position": (("adv_drives", "avg_field_position"),),
    "explosive_rate": (("adv_team", "EPA_explosive_rate"),),
}


@dataclass(frozen=True)
class CFBHistorySchemaCompatReport:
    contract: str
    status: str
    required_metrics: tuple[str, ...]
    directly_or_opponent_derivable: tuple[str, ...]
    missing_required_metrics: tuple[str, ...]
    point_in_time_proven: bool
    promotion_evidence: bool
    model_p_created: bool
    eligibility_changed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def audit_cfb_history_schema_compat(
    *,
    columns_by_dataset: Mapping[str, Iterable[str]],
    point_in_time_proven: bool = False,
) -> CFBHistorySchemaCompatReport:
    """Check exact field coverage without inventing unavailable metrics."""
    if type(point_in_time_proven) is not bool:
        raise ValueError("CFB_SCHEMA_COMPAT_PIT_BOOL_REQUIRED")

    normalized = {
        str(dataset): frozenset(str(column) for column in columns)
        for dataset, columns in columns_by_dataset.items()
    }
    available: list[str] = []
    missing: list[str] = []

    for metric in REQUIRED_TEAM_METRICS:
        recipes = RECIPES[metric]
        if not recipes:
            missing.append(metric)
            continue
        ok = True
        for dataset, column in recipes:
            base_dataset = dataset.removesuffix("_opponent_join")
            if column not in normalized.get(base_dataset, frozenset()):
                ok = False
                break
        (available if ok else missing).append(metric)

    # A complete source schema is necessary but never sufficient for promotion;
    # PIT and all downstream evidence are separate gates.
    complete = not missing
    return CFBHistorySchemaCompatReport(
        contract=CFB_HISTORY_SCHEMA_COMPAT_V1,
        status="SOURCE_SCHEMA_COMPATIBLE" if complete else "SOURCE_SCHEMA_INCOMPLETE",
        required_metrics=REQUIRED_TEAM_METRICS,
        directly_or_opponent_derivable=tuple(available),
        missing_required_metrics=tuple(missing),
        point_in_time_proven=point_in_time_proven,
        promotion_evidence=False,
        model_p_created=False,
        eligibility_changed=False,
    )
